"""Stage 2a: per-station + per-network daily accuracy statistics.

Reads the Stage-1 ``epoch_errors`` Parquet for one DOY, joins against
the station registry, and writes two long-format Parquets:

    accuracy/{mode}/{year}/{YYYYMMDD}.parquet
        per-station × window long form. ALL stations included; the
        consumer (network agg or report) decides which subset to use.

    accuracy_network/{mode}/{year}/{YYYYMMDD}.parquet
        per-network × scope × station_set × window cube
        13 networks × 4 scopes × 3 station_sets × 3 windows = 468 rows
        per (date, mode). Includes "all" network and the legacy
        "outside_wo_southern" scope for direct apples-to-apples
        comparison with QSS Performance Reports.

Notes
-----
- Percentiles are taken over **all epochs** within a group (Q=1
  included), matching legacy methodology. ``fix_rate`` is the
  separate metric for "how often did we have a Q=4 solution".
- Station-set semantics:
    eval_only — registry.is_eval == True
    qualified — registry.qualified == True (= is_eval until QC ships)
    all       — every station with at least one epoch
"""
from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import _registry

logger = logging.getLogger(__name__)

DEFAULT_EPOCH_ERRORS_ROOT = Path("data/processed/epoch_errors")
DEFAULT_OUTPUT_ROOT = Path("data/processed")
DEFAULT_PROVENANCE_PATH = Path("data/metadata/accuracy_stats.jsonl")

WINDOWS = ("all", "day", "night")
SCOPES = ("all", "inside", "outside", "outside_wo_southern")
STATION_SETS = ("eval_only", "qualified", "all")
NETWORK_IDS_INDIVIDUAL = tuple(str(i) for i in range(1, 13))
NETWORK_IDS = NETWORK_IDS_INDIVIDUAL + ("all",)

_PERCENTILES = (50, 95, 99, 99.9)


@dataclass(frozen=True)
class AccuracyDailyResult:
    target_date: date
    mode: str
    engine_version: str
    station_parquet: Path
    network_parquet: Path
    n_stations: int
    n_epochs: int
    n_qualified_stations: int


# ---------------------------------------------------------------------------
# Group-level metric kernel
# ---------------------------------------------------------------------------

def _group_stats(
    horizontal: np.ndarray,
    vertical: np.ndarray,
    quality: np.ndarray,
    num_sat: np.ndarray,
    *,
    n_stations: int | None = None,
) -> dict[str, float]:
    """Common metric kernel used by both station and network aggregations."""
    n = horizontal.size
    base: dict[str, float] = {
        "n_epoch": float(n),
        "n_sat_mean": float("nan") if n == 0 else float(np.mean(num_sat)),
        "fix_rate": float("nan") if n == 0 else float(np.mean(quality == 4)),
    }
    if n_stations is not None:
        base["n_stations"] = float(n_stations)
    if n == 0:
        for axis in ("hor", "ver"):
            for p in _PERCENTILES:
                base[f"{axis}_p{int(p)}" if p == int(p) else f"{axis}_p{int(p*10)}"] = float("nan")
            base[f"{axis}_rms"] = float("nan")
        return base
    for axis_name, vals in (("hor", horizontal), ("ver", vertical)):
        pcs = np.percentile(vals, _PERCENTILES)
        # Column naming: hor_p50, hor_p95, hor_p99, hor_p999.
        base[f"{axis_name}_p50"] = float(pcs[0])
        base[f"{axis_name}_p95"] = float(pcs[1])
        base[f"{axis_name}_p99"] = float(pcs[2])
        base[f"{axis_name}_p999"] = float(pcs[3])
        base[f"{axis_name}_rms"] = float(np.sqrt(np.mean(vals ** 2)))
    return base


# ---------------------------------------------------------------------------
# Per-station daily
# ---------------------------------------------------------------------------

def compute_station_accuracy(
    epoch_errors: pd.DataFrame,
    *,
    target_date: date,
    mode: str,
    engine_version: str,
) -> pd.DataFrame:
    """Per-station × per-window daily accuracy stats.

    Returns long-format DataFrame: one row per (station, window).
    """
    rows: list[dict] = []
    grouped = epoch_errors.groupby("station", sort=True)
    for station, sub in grouped:
        for window in WINDOWS:
            if window == "day":
                w = sub[sub["is_day"]]
            elif window == "night":
                w = sub[~sub["is_day"]]
            else:
                w = sub
            stats = _group_stats(
                w["horizontal_m"].to_numpy(),
                w["vertical_m"].to_numpy(),
                w["quality"].to_numpy(),
                w["num_sat"].to_numpy(),
            )
            rows.append({
                "date": target_date.isoformat(),
                "station": station,
                "mode": mode,
                "engine_version": engine_version,
                "window": window,
                **stats,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Per-network daily (cube)
# ---------------------------------------------------------------------------

def _select_scope(joined: pd.DataFrame, scope: str) -> pd.DataFrame:
    if scope == "all":
        return joined
    if scope == "inside":
        return joined[joined["isinside"]]
    if scope == "outside":
        return joined[~joined["isinside"]]
    if scope == "outside_wo_southern":
        return joined[(~joined["isinside"]) & (~joined["is_southern"])]
    raise ValueError(f"unknown scope: {scope}")


def _select_station_set(joined: pd.DataFrame, station_set: str) -> pd.DataFrame:
    if station_set == "all":
        return joined
    if station_set == "eval_only":
        return joined[joined["is_eval"]]
    if station_set == "qualified":
        return joined[joined["qualified"]]
    raise ValueError(f"unknown station_set: {station_set}")


def _select_window(joined: pd.DataFrame, window: str) -> pd.DataFrame:
    if window == "all":
        return joined
    if window == "day":
        return joined[joined["is_day"]]
    if window == "night":
        return joined[~joined["is_day"]]
    raise ValueError(f"unknown window: {window}")


def compute_network_accuracy(
    epoch_errors: pd.DataFrame,
    registry: pd.DataFrame,
    *,
    target_date: date,
    mode: str,
    engine_version: str,
) -> pd.DataFrame:
    """Per-network × scope × station_set × window long-format DataFrame.

    13 networks × 4 scopes × 3 station_sets × 3 windows = 468 rows.
    Empty cells get NaN metrics with ``n_stations = 0``.
    """
    reg_cols = ["rinex_id", "netid", "isinside", "is_eval", "qualified", "is_southern"]
    joined = epoch_errors.merge(
        registry[reg_cols],
        left_on="station", right_on="rinex_id", how="inner",
    )

    rows: list[dict] = []
    for network_id in NETWORK_IDS:
        if network_id == "all":
            base = joined
        else:
            base = joined[joined["netid"] == int(network_id)]
        for scope in SCOPES:
            base_scope = _select_scope(base, scope)
            for station_set in STATION_SETS:
                base_set = _select_station_set(base_scope, station_set)
                for window in WINDOWS:
                    sub = _select_window(base_set, window)
                    n_stations = int(sub["station"].nunique())
                    stats = _group_stats(
                        sub["horizontal_m"].to_numpy(),
                        sub["vertical_m"].to_numpy(),
                        sub["quality"].to_numpy(),
                        sub["num_sat"].to_numpy(),
                        n_stations=n_stations,
                    )
                    rows.append({
                        "date": target_date.isoformat(),
                        "mode": mode,
                        "engine_version": engine_version,
                        "network_id": network_id,
                        "scope": scope,
                        "station_set": station_set,
                        "window": window,
                        **stats,
                    })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def epoch_errors_path(target: date, mode: str, root: Path = DEFAULT_EPOCH_ERRORS_ROOT) -> Path:
    return root / mode / f"{target.year}" / f"{target.strftime('%Y%m%d')}.parquet"


def output_paths(
    target: date, mode: str, root: Path = DEFAULT_OUTPUT_ROOT,
) -> tuple[Path, Path]:
    suffix = f"{mode}/{target.year}/{target.strftime('%Y%m%d')}.parquet"
    return root / "accuracy" / suffix, root / "accuracy_network" / suffix


def compute_daily(
    target_date: date,
    *,
    mode: str,
    engine_version: str = "unknown",
    epoch_errors_root: Path = DEFAULT_EPOCH_ERRORS_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    registry_sources: _registry.RegistrySources | None = None,
    qualification_path: Path | None = None,
    record_provenance: bool = True,
    provenance_path: Path | None = None,
) -> AccuracyDailyResult:
    """One-shot daily accuracy aggregation for a (mode, date) pair.

    Reads ``data/processed/epoch_errors/{mode}/{year}/{YYYYMMDD}.parquet``
    and writes the two output Parquets.
    """
    in_path = epoch_errors_path(target_date, mode, epoch_errors_root)
    if not in_path.is_file():
        raise FileNotFoundError(
            f"Stage-1 epoch_errors Parquet missing: {in_path}. "
            f"Run `pntmoni-pipeline analyze epoch-errors` first."
        )
    epoch_errors = pd.read_parquet(in_path)
    if epoch_errors.empty:
        raise RuntimeError(f"epoch_errors {in_path} is empty")

    # If engine_version was set per-row in Stage 1, prefer that.
    if "engine_version" in epoch_errors.columns:
        v = epoch_errors["engine_version"].iloc[0]
        if isinstance(v, str) and v:
            engine_version = v

    registry = _registry.load(
        target_date, sources=registry_sources, qualification_path=qualification_path,
    )

    station_df = compute_station_accuracy(
        epoch_errors,
        target_date=target_date, mode=mode, engine_version=engine_version,
    )
    network_df = compute_network_accuracy(
        epoch_errors, registry,
        target_date=target_date, mode=mode, engine_version=engine_version,
    )

    out_station, out_network = output_paths(target_date, mode, output_root)
    for path, df in ((out_station, station_df), (out_network, network_df)):
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)

    n_qualified = int(registry["qualified"].sum())
    result = AccuracyDailyResult(
        target_date=target_date,
        mode=mode,
        engine_version=engine_version,
        station_parquet=out_station,
        network_parquet=out_network,
        n_stations=int(epoch_errors["station"].nunique()),
        n_epochs=int(len(epoch_errors)),
        n_qualified_stations=n_qualified,
    )
    logger.info(
        "accuracy daily: wrote %s + %s (stations=%d epochs=%d qualified=%d)",
        out_station, out_network,
        result.n_stations, result.n_epochs, result.n_qualified_stations,
    )
    if record_provenance:
        _record_provenance(result, provenance_path or DEFAULT_PROVENANCE_PATH)
    return result


def _record_provenance(res: AccuracyDailyResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "target_date": res.target_date.isoformat(),
        "mode": res.mode,
        "engine_version": res.engine_version,
        "n_stations": res.n_stations,
        "n_epochs": res.n_epochs,
        "n_qualified_stations": res.n_qualified_stations,
        "station_parquet": str(res.station_parquet),
        "network_parquet": str(res.network_parquet),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


__all__ = [
    "AccuracyDailyResult",
    "DEFAULT_EPOCH_ERRORS_ROOT",
    "DEFAULT_OUTPUT_ROOT",
    "NETWORK_IDS",
    "SCOPES",
    "STATION_SETS",
    "WINDOWS",
    "compute_daily",
    "compute_network_accuracy",
    "compute_station_accuracy",
]
