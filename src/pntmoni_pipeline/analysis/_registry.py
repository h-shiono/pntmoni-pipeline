"""Station registry — joins network_assignments + network_info + eval_periods.

The registry resolves per-station qualification flags for a given
target date. ``is_eval`` is computed by walking each station's eval
periods and matching ``from <= target_date <= to``. ``qc_pass`` is a
placeholder for the QC framework (Backlog #2) — until that ships,
``qc_pass`` is ``None`` everywhere and ``qualified`` reduces to
``is_eval``.

When the QC framework lands, ``qualified = is_eval | qc_pass``
(matching the legacy `valid | is_eval` predicate).
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
) -> pd.DataFrame:
    """Return a one-row-per-station registry DataFrame for ``target_date``.

    Columns:
        rinex_id, netid (Int64 nullable), isinside (bool),
        is_eval (bool, resolved from eval_periods at target_date),
        qc_pass (object — None placeholder until QC framework ships),
        qualified (bool: is_eval OR qc_pass==True; equals is_eval today),
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
            "qc_pass": None,                     # populated by QC framework, future
            # qualified semantics: is_eval | qc_pass==True. With qc_pass
            # currently None, it collapses to is_eval (no false positives).
            "qualified": is_eval_now,
            "is_southern": netid in SOUTHERN_NETIDS if netid is not None else False,
        })

    df = pd.DataFrame(rows)
    # Use Int64 (pandas nullable) so missing netid stays explicit.
    if "netid" in df:
        df["netid"] = df["netid"].astype("Int64")
    return df


__all__ = [
    "DEFAULT_EVAL_PERIODS",
    "DEFAULT_NETWORK_ASSIGNMENTS",
    "DEFAULT_NETWORK_INFO",
    "RegistrySources",
    "SOUTHERN_NETIDS",
    "load",
]
