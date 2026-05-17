"""Station registry — joins network_assignments + network_info + eval_periods.

The registry resolves per-station qualification flags for a given
target date. ``is_eval`` is computed by walking each station's eval
periods and matching ``from <= target_date <= to``. ``qc_pass`` is a
placeholder for the QC framework — until QC fully ships, ``qc_pass``
is ``None`` everywhere and ``qualified`` reduces to ``is_eval``.

Optional override: when ``load(qualification_path=...)`` is supplied,
the registry merges a previously-computed station_qualification
parquet (produced by ``analysis.qualification.qualify()``) over the
period-derived defaults. The parquet's flags take precedence per
station:

- ``is_eval``   ← ``force_eval``  (CLAS 72 with latest-period fallback,
                                    matching qual-v2 semantics)
- ``qc_pass``   ← ``qc_pass``    (rolling-QC outcome)
- ``qualified`` ← ``qualified``  (``(qc_pass | force_eval) & ~out_of_service``)
- ``out_of_service`` is added as a new column when present

The merge supports the Monthly 速報 use case where the latest QSS
Service Performance Report period (e.g. fy2025_1st_h, Apr–Sep 2025) is
treated as the operative eval set for a target date past the
period's natural end (per ADR 0013's 速報 framing — the report does
not wait for fy2026 publication).
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

if sys.version_info >= (3, 11):
    import tomllib
else:                                                 # pragma: no cover
    import tomli as tomllib

logger = logging.getLogger(__name__)

DEFAULT_NETWORK_ASSIGNMENTS = Path("configs/stations/network_assignments.toml")
DEFAULT_NETWORK_INFO = Path("configs/stations/network_info.toml")
DEFAULT_EVAL_PERIODS = Path("configs/stations/eval_periods.toml")
SOUTHERN_NETIDS: frozenset[int] = frozenset({1, 2, 12})


@dataclass(frozen=True)
class RegistrySources:
    network_assignments: Path = DEFAULT_NETWORK_ASSIGNMENTS
    network_info: Path = DEFAULT_NETWORK_INFO
    eval_periods: Path = DEFAULT_EVAL_PERIODS


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        logger.warning("registry source missing: %s", path)
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _is_eval_at(periods: list[dict[str, Any]], target: date) -> bool:
    for p in periods:
        f, t = p.get("from"), p.get("to")
        if isinstance(f, date) and isinstance(t, date) and f <= target <= t:
            return True
    return False


def load(
    target_date: date,
    *,
    sources: RegistrySources | None = None,
    qualification_path: Path | None = None,
) -> pd.DataFrame:
    """Return a one-row-per-station registry DataFrame for ``target_date``.

    Columns:
        rinex_id, netid (Int64 nullable), isinside (bool),
        is_eval (bool, resolved from eval_periods at target_date — or
            from the qualification parquet's ``force_eval`` when merged),
        qc_pass (object — None unless a qualification parquet is merged),
        qualified (bool: defaults to is_eval; the parquet's
            ``qualified`` column overrides per station when merged),
        out_of_service (bool, only present when a qualification parquet
            is merged; absent otherwise),
        is_southern (bool: netid ∈ {1, 2, 12}; convenience for the
            "outside_wo_southern" network scope).
    """
    src = sources or RegistrySources()
    na_doc = _load_toml(src.network_assignments).get("stations", {})
    ev_doc = _load_toml(src.eval_periods).get("stations", {})
    # network_info isn't a column source for the registry frame itself —
    # callers can join it back if they need grid weights — but we keep
    # the source listed for provenance.

    rows: list[dict[str, Any]] = []
    all_ids = set(na_doc) | set(ev_doc)
    for rid in sorted(all_ids):
        na = na_doc.get(rid, {})
        periods = ev_doc.get(rid, {}).get("periods", [])
        netid = na.get("netid")
        is_eval_now = _is_eval_at(periods, target_date)
        rows.append({
            "rinex_id": rid,
            "netid": netid,
            "isinside": bool(na.get("isinside", False)),
            "is_eval": is_eval_now,
            "qc_pass": None,
            "qualified": is_eval_now,
            "is_southern": netid in SOUTHERN_NETIDS if netid is not None else False,
        })

    df = pd.DataFrame(rows)
    if "netid" in df:
        df["netid"] = df["netid"].astype("Int64")

    if qualification_path is not None:
        df = _merge_qualification(df, qualification_path)
    return df


def _merge_qualification(df: pd.DataFrame, path: Path) -> pd.DataFrame:
    """Override is_eval / qc_pass / qualified / add out_of_service from
    a station_qualification parquet (per :mod:`.qualification`).

    The parquet has one row per ``station`` with boolean columns
    ``qc_pass``, ``force_eval``, ``out_of_service``, ``qualified``.
    Stations present in the parquet have their flags overridden;
    stations absent are left at the registry's period-derived defaults.
    """
    if not path.is_file():
        raise FileNotFoundError(f"qualification parquet missing: {path}")
    q = pd.read_parquet(path)
    expected = {"station", "qc_pass", "force_eval", "out_of_service", "qualified"}
    missing = expected - set(q.columns)
    if missing:
        raise ValueError(
            f"qualification parquet {path} missing columns: {sorted(missing)}"
        )
    q = q.rename(columns={"station": "rinex_id"})[
        ["rinex_id", "qc_pass", "force_eval", "out_of_service", "qualified"]
    ]
    n_q = len(q)
    n_in_registry = q["rinex_id"].isin(df["rinex_id"]).sum()
    logger.info(
        "registry: merging qualification %s — %d rows, %d match registry",
        path, n_q, n_in_registry,
    )

    merged = df.merge(q, on="rinex_id", how="left", suffixes=("", "_q"))
    # Override per-station only where the parquet has a row.
    mask = merged["qualified_q"].notna()
    merged.loc[mask, "is_eval"] = merged.loc[mask, "force_eval"].astype(bool)
    merged.loc[mask, "qc_pass"] = merged.loc[mask, "qc_pass_q"].astype("boolean")
    merged.loc[mask, "qualified"] = merged.loc[mask, "qualified_q"].astype(bool)
    # Out-of-service: True only for stations in parquet and flagged;
    # absent stations get False (could not be vetoed by parquet we don't have).
    merged["out_of_service"] = (
        merged["out_of_service"].fillna(False).astype(bool)
    )
    return merged.drop(columns=["qc_pass_q", "force_eval", "qualified_q"])


__all__ = [
    "DEFAULT_EVAL_PERIODS",
    "DEFAULT_NETWORK_ASSIGNMENTS",
    "DEFAULT_NETWORK_INFO",
    "RegistrySources",
    "SOUTHERN_NETIDS",
    "load",
]
