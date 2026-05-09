"""Stage 2b: per-station + per-network daily TTFF statistics (strict).

Reads the same Stage-1 ``epoch_errors`` Parquet that the accuracy
aggregator reads. For each station × reset window:

- Identify the reset boundary (epoch index multiples of
  ``reset_period_sec / sampling_interval_sec``).
- Find the first epoch within the window that satisfies the strict
  TTFF criterion::

      Q == 4 AND horizontal_m <= H AND vertical_m <= V

  with H, V from :mod:`analysis._coords_math` mode-aware thresholds
  (kinematic: H=0.12 V=0.24, static: H=0.06 V=0.12 — legacy values).
  This matches the QSS Performance Report methodology and is stricter
  than the simple "first Q=4" definition used by the earlier
  :mod:`analysis._ttff` module (kept for backward compatibility).

Outputs two long-format Parquets analogous to the accuracy aggregator:

    ttff/{mode}/{year}/{YYYYMMDD}.parquet
        per-station × window long form. Metrics include
        ``ttff_p50, p90, p95, p99``, ``fix_success_rate``,
        ``n_windows_fixed``, ``n_windows``.

    ttff_network/{mode}/{year}/{YYYYMMDD}.parquet
        per-network × scope × station_set × window cube
        (13 × 4 × 3 × 3 = 468 cells).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import _accuracy_stats, _coords_math, _registry

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_ROOT = Path("data/processed")
DEFAULT_PROVENANCE_PATH = Path("data/metadata/ttff_stats.jsonl")
DEFAULT_RESET_PERIOD_SEC = 900     # ADR 0005 primary
DEFAULT_SAMPLING_INTERVAL_SEC = 30
DEFAULT_MIN_WINDOW_COMPLETION = 0.9  # follow legacy: drop stations with <90% epochs

_TTFF_PERCENTILES = (50, 90, 95, 99)


@dataclass(frozen=True)
class TTFFDailyResult:
    target_date: date
    mode: str
    engine_version: str
    station_parquet: Path
    network_parquet: Path
    n_stations: int
    n_qualified_stations: int
    reset_period_sec: int
    horizontal_threshold_m: float
    vertical_threshold_m: float


# ---------------------------------------------------------------------------
# Per-station TTFF events (strict)
# ---------------------------------------------------------------------------

def _ttff_per_station(
    station_df: pd.DataFrame,
    *,
    reset_period_sec: int,
    sampling_interval_sec: int,
    horizontal_threshold_m: float,
    vertical_threshold_m: float,
    n_windows: int,
) -> pd.DataFrame:
    """Per-window strict-TTFF event for one station.

    Returns DataFrame with columns ``window_idx`` and ``ttff_sec``
    (NaN for unfixed windows). The "window" here means a 15-min reset
    window (or whatever ``reset_period_sec`` says), NOT the day/night
    split — that's added in :func:`compute_station_ttff` below.
    """
    epochs_per_window = reset_period_sec // sampling_interval_sec
    # Build a sparse map (epoch_idx → row idx in station_df) so gaps in
    # observation don't drift our window boundaries.
    eidx = station_df["epoch_idx"].to_numpy()
    qual = station_df["quality"].to_numpy()
    hor = station_df["horizontal_m"].to_numpy()
    ver = station_df["vertical_m"].to_numpy()
    pos = {int(i): k for k, i in enumerate(eidx)}

    ttff_secs = np.full(n_windows, np.nan, dtype=np.float64)
    for w in range(n_windows):
        start = w * epochs_per_window
        end = start + epochs_per_window
        for j in range(start, end):
            k = pos.get(j)
            if k is None:
                continue
            if (
                qual[k] == 4
                and hor[k] <= horizontal_threshold_m
                and ver[k] <= vertical_threshold_m
            ):
                ttff_secs[w] = (j - start) * sampling_interval_sec
                break
    return pd.DataFrame({
        "window_idx": np.arange(n_windows),
        "ttff_sec": ttff_secs,
    })


# ---------------------------------------------------------------------------
# Day/night classification of each reset window
# ---------------------------------------------------------------------------

def _window_is_day(window_idx: int, sampling_interval_sec: int, reset_period_sec: int) -> bool:
    """Treat the *start* of the reset window as the indicator of day/night.

    Window ``w`` begins at GPST seconds-of-day ``w * reset_period_sec``,
    which translates back to UTC ``(seconds_of_day - leap_seconds) % 86400``.
    Day = legacy DAY_HOURS_UTC.
    """
    start_sod_gpst = window_idx * reset_period_sec
    start_sod_utc = (start_sod_gpst - _coords_math.LEAP_SECONDS) % 86400
    hour_utc = start_sod_utc // 3600
    from ._epoch_errors import DAY_HOURS_UTC
    return int(hour_utc) in DAY_HOURS_UTC


# ---------------------------------------------------------------------------
# Per-station TTFF aggregation
# ---------------------------------------------------------------------------

def compute_station_ttff(
    epoch_errors: pd.DataFrame,
    *,
    target_date: date,
    mode: str,
    engine_version: str,
    reset_period_sec: int,
    sampling_interval_sec: int,
    horizontal_threshold_m: float,
    vertical_threshold_m: float,
    min_window_completion: float = DEFAULT_MIN_WINDOW_COMPLETION,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-station daily TTFF stats (long).

    Returns ``(station_summary_df, station_events_df)`` where the events
    frame is keyed by (station, window_idx) and is the input the network
    cube reads from. The summary frame has one row per (station, window)
    × ``window ∈ {all, day, night}``.
    """
    n_windows_total = (24 * 3600) // reset_period_sec
    epochs_per_window = reset_period_sec // sampling_interval_sec
    expected_epochs_full = n_windows_total * epochs_per_window
    completion_threshold = min_window_completion * expected_epochs_full

    is_day_per_window = np.array(
        [_window_is_day(w, sampling_interval_sec, reset_period_sec) for w in range(n_windows_total)],
        dtype=bool,
    )

    summary_rows: list[dict] = []
    events_rows: list[pd.DataFrame] = []
    for station, sub in epoch_errors.groupby("station", sort=True):
        events = _ttff_per_station(
            sub,
            reset_period_sec=reset_period_sec,
            sampling_interval_sec=sampling_interval_sec,
            horizontal_threshold_m=horizontal_threshold_m,
            vertical_threshold_m=vertical_threshold_m,
            n_windows=n_windows_total,
        )
        events["station"] = station
        events["is_day"] = is_day_per_window
        events_rows.append(events)

        n_obs = int(len(sub))
        completion = n_obs / expected_epochs_full
        for window_label in _accuracy_stats.WINDOWS:
            if window_label == "day":
                ev = events[events["is_day"]]
            elif window_label == "night":
                ev = events[~events["is_day"]]
            else:
                ev = events
            n_w = int(len(ev))
            n_fixed = int(ev["ttff_sec"].notna().sum())
            ttff_vals = ev["ttff_sec"].dropna().to_numpy()
            row = {
                "date": target_date.isoformat(),
                "station": station,
                "mode": mode,
                "engine_version": engine_version,
                "window": window_label,
                "n_windows": n_w,
                "n_windows_fixed": n_fixed,
                "fix_success_rate": (n_fixed / n_w) if n_w else float("nan"),
                "n_obs_epochs": n_obs,
                "completion": completion,
                "passes_completion_gate": completion >= min_window_completion,
            }
            for p in _TTFF_PERCENTILES:
                key = f"ttff_p{int(p)}_sec"
                row[key] = float(np.percentile(ttff_vals, p)) if ttff_vals.size else float("nan")
            summary_rows.append(row)

    if events_rows:
        events_df = pd.concat(events_rows, ignore_index=True)
    else:
        events_df = pd.DataFrame(columns=["station", "window_idx", "ttff_sec", "is_day"])
    return pd.DataFrame(summary_rows), events_df


# ---------------------------------------------------------------------------
# Per-network TTFF cube
# ---------------------------------------------------------------------------

def compute_network_ttff(
    events: pd.DataFrame,
    registry: pd.DataFrame,
    completion_by_station: dict[str, float],
    *,
    target_date: date,
    mode: str,
    engine_version: str,
    reset_period_sec: int,
    min_window_completion: float = DEFAULT_MIN_WINDOW_COMPLETION,
) -> pd.DataFrame:
    """Per-network × scope × station_set × window TTFF cube (468 cells)."""
    # Drop stations whose data completion is below the gate (legacy 90 %).
    qualified_stations = {
        s for s, c in completion_by_station.items()
        if c >= min_window_completion
    }
    events = events[events["station"].isin(qualified_stations)]

    reg_cols = ["rinex_id", "netid", "isinside", "is_eval", "qualified", "is_southern"]
    joined = events.merge(
        registry[reg_cols], left_on="station", right_on="rinex_id", how="inner",
    )

    rows: list[dict] = []
    for network_id in _accuracy_stats.NETWORK_IDS:
        if network_id == "all":
            base = joined
        else:
            base = joined[joined["netid"] == int(network_id)]
        for scope in _accuracy_stats.SCOPES:
            base_scope = _accuracy_stats._select_scope(base, scope)
            for station_set in _accuracy_stats.STATION_SETS:
                base_set = _accuracy_stats._select_station_set(base_scope, station_set)
                for window in _accuracy_stats.WINDOWS:
                    if window == "day":
                        sub = base_set[base_set["is_day"]]
                    elif window == "night":
                        sub = base_set[~base_set["is_day"]]
                    else:
                        sub = base_set
                    n_stations = int(sub["station"].nunique())
                    ttff_vals = sub["ttff_sec"].dropna().to_numpy()
                    n_windows = int(len(sub))
                    n_fixed = int(ttff_vals.size)
                    row = {
                        "date": target_date.isoformat(),
                        "mode": mode,
                        "engine_version": engine_version,
                        "network_id": network_id,
                        "scope": scope,
                        "station_set": station_set,
                        "window": window,
                        "n_stations": n_stations,
                        "n_windows": n_windows,
                        "n_windows_fixed": n_fixed,
                        "fix_success_rate": (n_fixed / n_windows) if n_windows else float("nan"),
                    }
                    for p in _TTFF_PERCENTILES:
                        key = f"ttff_p{int(p)}_sec"
                        row[key] = (
                            float(np.percentile(ttff_vals, p)) if ttff_vals.size else float("nan")
                        )
                    rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def output_paths(
    target: date, mode: str, root: Path = DEFAULT_OUTPUT_ROOT,
) -> tuple[Path, Path]:
    suffix = f"{mode}/{target.year}/{target.strftime('%Y%m%d')}.parquet"
    return root / "ttff" / suffix, root / "ttff_network" / suffix


def compute_daily(
    target_date: date,
    *,
    mode: str,
    engine_version: str = "unknown",
    epoch_errors_root: Path = _accuracy_stats.DEFAULT_EPOCH_ERRORS_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    reset_period_sec: int = DEFAULT_RESET_PERIOD_SEC,
    sampling_interval_sec: int = DEFAULT_SAMPLING_INTERVAL_SEC,
    horizontal_threshold_m: float | None = None,
    vertical_threshold_m: float | None = None,
    min_window_completion: float = DEFAULT_MIN_WINDOW_COMPLETION,
    registry_sources: _registry.RegistrySources | None = None,
    record_provenance: bool = True,
    provenance_path: Path | None = None,
) -> TTFFDailyResult:
    """Daily strict-TTFF aggregation for one (mode, date) pair."""
    if horizontal_threshold_m is None or vertical_threshold_m is None:
        thr = _coords_math.thresholds_for_mode(mode)
        if horizontal_threshold_m is None:
            horizontal_threshold_m = thr.horizontal_m
        if vertical_threshold_m is None:
            vertical_threshold_m = thr.vertical_m

    in_path = _accuracy_stats.epoch_errors_path(target_date, mode, epoch_errors_root)
    if not in_path.is_file():
        raise FileNotFoundError(
            f"Stage-1 epoch_errors Parquet missing: {in_path}. "
            f"Run `pntmoni-pipeline analyze epoch-errors` first."
        )
    epoch_errors = pd.read_parquet(in_path)
    if epoch_errors.empty:
        raise RuntimeError(f"epoch_errors {in_path} is empty")
    if "engine_version" in epoch_errors.columns:
        v = epoch_errors["engine_version"].iloc[0]
        if isinstance(v, str) and v:
            engine_version = v

    registry = _registry.load(target_date, sources=registry_sources)

    station_df, events_df = compute_station_ttff(
        epoch_errors,
        target_date=target_date, mode=mode, engine_version=engine_version,
        reset_period_sec=reset_period_sec,
        sampling_interval_sec=sampling_interval_sec,
        horizontal_threshold_m=horizontal_threshold_m,
        vertical_threshold_m=vertical_threshold_m,
        min_window_completion=min_window_completion,
    )

    epochs_per_window = reset_period_sec // sampling_interval_sec
    expected_epochs_full = (24 * 3600 // reset_period_sec) * epochs_per_window
    completion_by_station = {
        s: int(grp.shape[0]) / expected_epochs_full
        for s, grp in epoch_errors.groupby("station", sort=False)
    }

    network_df = compute_network_ttff(
        events_df, registry, completion_by_station,
        target_date=target_date, mode=mode, engine_version=engine_version,
        reset_period_sec=reset_period_sec,
        min_window_completion=min_window_completion,
    )

    out_station, out_network = output_paths(target_date, mode, output_root)
    for path, df in ((out_station, station_df), (out_network, network_df)):
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)

    n_qualified = int(registry["qualified"].sum())
    result = TTFFDailyResult(
        target_date=target_date,
        mode=mode,
        engine_version=engine_version,
        station_parquet=out_station,
        network_parquet=out_network,
        n_stations=int(epoch_errors["station"].nunique()),
        n_qualified_stations=n_qualified,
        reset_period_sec=reset_period_sec,
        horizontal_threshold_m=horizontal_threshold_m,
        vertical_threshold_m=vertical_threshold_m,
    )
    logger.info(
        "ttff daily: wrote %s + %s (stations=%d qualified=%d "
        "thresholds H=%.3f V=%.3f reset=%ds)",
        out_station, out_network,
        result.n_stations, result.n_qualified_stations,
        horizontal_threshold_m, vertical_threshold_m, reset_period_sec,
    )
    if record_provenance:
        _record_provenance(result, provenance_path or DEFAULT_PROVENANCE_PATH)
    return result


def _record_provenance(res: TTFFDailyResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "target_date": res.target_date.isoformat(),
        "mode": res.mode,
        "engine_version": res.engine_version,
        "reset_period_sec": res.reset_period_sec,
        "horizontal_threshold_m": res.horizontal_threshold_m,
        "vertical_threshold_m": res.vertical_threshold_m,
        "n_stations": res.n_stations,
        "n_qualified_stations": res.n_qualified_stations,
        "station_parquet": str(res.station_parquet),
        "network_parquet": str(res.network_parquet),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


__all__ = [
    "DEFAULT_RESET_PERIOD_SEC",
    "DEFAULT_SAMPLING_INTERVAL_SEC",
    "DEFAULT_MIN_WINDOW_COMPLETION",
    "TTFFDailyResult",
    "compute_daily",
    "compute_network_ttff",
    "compute_station_ttff",
]
