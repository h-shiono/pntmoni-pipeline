"""Reference coordinates from GSI F5 (15-day robust median, ECEF).

Per the design recorded in :file:`tasks/lessons.md`:

- GSI's F5 publishes daily coordinates of every GEONET station, solved
  *relative* to the network's anchor station (default 92110, Tsukuba1).
- The fixed station's absolute coordinate occasionally jumps when an
  IGS product gap perturbs the day's processing. Those days are
  dropped (NaN'd) before computing its median absolute.
- Other stations' absolute coordinates jump *together* with the fixed
  station on those days — so the per-day relative
  ``station_xyz_i − fixed_xyz_i`` is invariant across jumps. Therefore
  jump filtering applies only to the fixed station's absolute median;
  per-day relatives are taken over the full window.

Algorithm (Common-Mode Removal)::

    fixed_truth      = nanmedian(fixed_xyz_in_window     with jump days NaN'd)
    relative_per_day = station_xyz_in_window − fixed_xyz_in_window  (per day, no NaN)
    station_truth    = nanmedian(relative_per_day) + fixed_truth

This is a deviation from the reference toolbox's ``make_coord.py``,
which subtracts the *median* fixed coord rather than the per-day
fixed value (Method A). Method B (per-day) actively cancels common-
mode drift even on days when the fixed station's absolute is off.
"""
from __future__ import annotations

import logging
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from . import _f5_reader

if sys.version_info >= (3, 11):
    import tomllib
else:                                                 # pragma: no cover
    import tomli as tomllib

logger = logging.getLogger(__name__)

DEFAULT_FIXED_STATION_ID = "92110"          # Tsukuba1 (TSUKUBA1)
DEFAULT_WINDOW_DAYS = 7                     # ±7 days → 15-day window
DEFAULT_JUMPS_PATH = Path("configs/gsi_jumps.toml")
DEFAULT_F5_ROOT = Path("data/raw/f5")
DEFAULT_OUTPUT_ROOT = Path("data/processed/reference_coords")
DEFAULT_PROVENANCE_PATH = Path("data/metadata/reference_coords.jsonl")

# Reference-coordinate methodology identifiers (methodology §3.2, §7.2).
# ±7-day (15 calendar day) centered median with common-mode removal,
# operating on GSI daily solutions (product recorded via ``variant``).
METHODOLOGY_VERSION = "gsi-daily-median15d-1.0"
FILTER_METHOD = "median15d-centered"

# Minimum non-NaN fixed-station days required for a "production-grade"
# reference. Default is 14 (out of 15 in a ±7d window), which permits
# AT MOST one jump-NaN'd day. Partial-window runs (typical when F5
# publication has not caught up) drop below this threshold and require
# the explicit ``--allow-partial-window`` flag.
DEFAULT_MIN_FIXED_DAYS = 14


# ---------------------------------------------------------------------------
# Jump-list loading
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FixedStationJump:
    date: date
    fixed_station_id: str
    reason: str
    recorded_at: str | None = None


def load_jumps(path: Path | None = None) -> list[FixedStationJump]:
    """Load curated jump list from a TOML file. Empty if file missing."""
    p = path or DEFAULT_JUMPS_PATH
    if not p.is_file():
        logger.warning("no jumps TOML at %s — proceeding with empty jump list", p)
        return []
    with p.open("rb") as f:
        doc = tomllib.load(f)
    out: list[FixedStationJump] = []
    for entry in doc.get("jumps", []):
        d = entry["date"]
        if isinstance(d, str):
            d = date.fromisoformat(d)
        out.append(FixedStationJump(
            date=d,
            fixed_station_id=entry.get("fixed_station_id", DEFAULT_FIXED_STATION_ID),
            reason=entry.get("reason", ""),
            recorded_at=entry.get("recorded_at"),
        ))
    return out


# ---------------------------------------------------------------------------
# Window helpers
# ---------------------------------------------------------------------------

def _window_dates(target: date, window_days: int) -> list[date]:
    return [target + timedelta(days=d) for d in range(-window_days, window_days + 1)]


def _years_in_window(target: date, window_days: int) -> set[int]:
    return {(target + timedelta(days=d)).year for d in range(-window_days, window_days + 1)}


def _load_fixed_station_window(
    f5_root: Path,
    fixed_station_id: str,
    target: date,
    window_days: int,
) -> pd.DataFrame:
    """Return the fixed station's daily series across the window's calendar.

    The DataFrame index is ``date`` (datetime64[ns, UTC]); columns are
    ``x_m``, ``y_m``, ``z_m``. Missing days inside the window are
    represented as rows of NaN (so per-day arithmetic stays aligned).
    """
    frames: list[pd.DataFrame] = []
    for year in sorted(_years_in_window(target, window_days)):
        candidate = _f5_reader.f5_path(f5_root, fixed_station_id, year)
        if not candidate.is_file():
            logger.warning("fixed station F5 missing: %s", candidate)
            continue
        f5 = _f5_reader.read_f5(candidate)
        frames.append(f5.df[["date", "x_m", "y_m", "z_m"]])
    if not frames:
        raise FileNotFoundError(
            f"no F5 files for fixed station {fixed_station_id} "
            f"around {target} (years tried: {sorted(_years_in_window(target, window_days))})"
        )
    fixed = pd.concat(frames, ignore_index=True).set_index("date").sort_index()

    # Reindex to the explicit window dates so missing days are NaN rows.
    window = pd.to_datetime(_window_dates(target, window_days), utc=True)
    return fixed.reindex(window)


def _apply_jumps_to_fixed(
    fixed_window: pd.DataFrame,
    jumps: Iterable[FixedStationJump],
    fixed_station_id: str,
) -> tuple[pd.DataFrame, list[date]]:
    """NaN out fixed-station rows on jump dates that match this station.

    Returns ``(filtered_df, applied_dates)``.
    """
    applied: list[date] = []
    df = fixed_window.copy()
    for j in jumps:
        if j.fixed_station_id not in (fixed_station_id, "*"):
            continue
        target_idx = pd.Timestamp(j.date, tz="UTC")
        if target_idx in df.index:
            df.loc[target_idx, ["x_m", "y_m", "z_m"]] = np.nan
            applied.append(j.date)
    return df, applied


# ---------------------------------------------------------------------------
# Per-station computation (common-mode removal)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ComputeResult:
    df: pd.DataFrame                 # one row per (target_date, station)
    fixed_metadata: _f5_reader.F5Metadata
    fixed_truth: tuple[float, float, float]
    n_fixed_days_used: int
    n_fixed_days_dropped: int
    applied_jump_dates: list[date]
    f5_sha256: dict[str, str]
    variant: str                     # "f5" | "f5_1" | "r5" | "r5_1"


def compute_for_target(
    target: date,
    *,
    f5_root: Path = DEFAULT_F5_ROOT,
    fixed_station_id: str = DEFAULT_FIXED_STATION_ID,
    window_days: int = DEFAULT_WINDOW_DAYS,
    jumps: Sequence[FixedStationJump] | None = None,
    allow_partial_window: bool = False,
    min_fixed_days: int = DEFAULT_MIN_FIXED_DAYS,
    variant: str = "f5_1",
) -> ComputeResult:
    """Compute reference coordinates for one target date.

    Reads every available F5 station for the years that the window
    spans, applies common-mode removal against the fixed station, and
    returns one row per station in ``result.df``.

    Parameters
    ----------
    allow_partial_window
        If True, accept a window where some target dates have no F5
        data (typical when the F5 publication has not caught up). The
        fixed station's median is still computed but uses fewer days.
    min_fixed_days
        Minimum non-NaN days required for the fixed station's median
        to be considered reliable. Below this, the function raises.
    """
    jumps = list(jumps or [])

    fixed_window_full = _load_fixed_station_window(
        f5_root, fixed_station_id, target, window_days,
    )
    fixed_filtered, applied_jumps = _apply_jumps_to_fixed(
        fixed_window_full, jumps, fixed_station_id,
    )

    n_present = int(fixed_filtered[["x_m", "y_m", "z_m"]].notna().all(axis=1).sum())
    n_dropped = len(fixed_filtered) - n_present

    if n_present < min_fixed_days and not allow_partial_window:
        raise RuntimeError(
            f"only {n_present}/{len(fixed_filtered)} fixed-station days available "
            f"for {target} (window ±{window_days}d). Pass allow_partial_window=True "
            f"to proceed; lower min_fixed_days={min_fixed_days} to relax."
        )

    fixed_xyz = fixed_filtered[["x_m", "y_m", "z_m"]].to_numpy()
    fixed_truth = np.nanmedian(fixed_xyz, axis=0)
    if np.any(np.isnan(fixed_truth)):
        raise RuntimeError(
            f"fixed station {fixed_station_id} median is NaN for {target}. "
            f"All {len(fixed_filtered)} window days were missing or NaN'd."
        )

    # Per-day fixed for common-mode removal (use UNFILTERED window here:
    # jump days are still aligned to "what fixed published that day", and
    # the same jump appears in every station's row, so per-day relative
    # is invariant across the jump).
    fixed_per_day = fixed_window_full[["x_m", "y_m", "z_m"]].to_numpy()
    window_index = fixed_window_full.index

    # Walk every station in the window's years.
    f5_sha256: dict[str, str] = {}
    metadata_by_id: dict[str, _f5_reader.F5Metadata] = {}
    rows: list[dict] = []
    seen_ids: set[str] = set()

    fixed_metadata: _f5_reader.F5Metadata | None = None

    for year in sorted(_years_in_window(target, window_days)):
        for path in _f5_reader.list_f5_files(f5_root, year):
            try:
                f5 = _f5_reader.read_f5(path)
            except Exception as exc:                 # pragma: no cover - defensive
                logger.warning("failed to read %s: %s", path, exc)
                continue
            f5_sha256[path.name] = f5.sha256
            sid = f5.metadata.f5_id
            if sid == fixed_station_id:
                fixed_metadata = f5.metadata
                # Skip — handled separately above; we still need its sha256.
                continue
            if sid in seen_ids:
                # Window crosses years and we already loaded this station
                # from a different year. Concatenate the new data.
                pass
            seen_ids.add(sid)
            metadata_by_id[sid] = f5.metadata

            # Align this station's data to the window grid; missing days
            # become NaN rows so per-day subtraction stays aligned.
            station = f5.df[["date", "x_m", "y_m", "z_m"]].set_index("date")
            station = station.reindex(window_index)
            station_xyz = station.to_numpy()

            # Per-day relative; NaN on either side propagates → ignored.
            relative = station_xyz - fixed_per_day
            n_valid = int((~np.isnan(relative).any(axis=1)).sum())
            if n_valid == 0:
                logger.debug("station %s: no overlapping days in window", sid)
                continue
            relative_median = np.nanmedian(relative, axis=0)
            station_truth = relative_median + fixed_truth

            rows.append({
                "f5_id": sid,
                "rinex_id": f5.metadata.rinex_id,
                "j_name": f5.metadata.j_name,
                "e_name": f5.metadata.e_name,
                "target_date": target.isoformat(),
                "x_m": float(station_truth[0]),
                "y_m": float(station_truth[1]),
                "z_m": float(station_truth[2]),
                "rel_x_m": float(relative_median[0]),
                "rel_y_m": float(relative_median[1]),
                "rel_z_m": float(relative_median[2]),
                "n_days_used": n_valid,
                "n_days_in_window": len(window_index),
                "frame": f5.metadata.frame,
            })

    if fixed_metadata is None:
        raise FileNotFoundError(
            f"fixed station F5 metadata not found (id={fixed_station_id})"
        )

    # Append the fixed station as its own row so consumers don't
    # special-case it. Its rel_xyz is (0, 0, 0) by construction.
    rows.append({
        "f5_id": fixed_metadata.f5_id,
        "rinex_id": fixed_metadata.rinex_id,
        "j_name": fixed_metadata.j_name,
        "e_name": fixed_metadata.e_name,
        "target_date": target.isoformat(),
        "x_m": float(fixed_truth[0]),
        "y_m": float(fixed_truth[1]),
        "z_m": float(fixed_truth[2]),
        "rel_x_m": 0.0,
        "rel_y_m": 0.0,
        "rel_z_m": 0.0,
        "n_days_used": n_present,
        "n_days_in_window": len(window_index),
        "frame": fixed_metadata.frame,
    })

    df = pd.DataFrame(rows).sort_values("f5_id").reset_index(drop=True)
    if not df.empty:
        df["variant"] = variant
    return ComputeResult(
        df=df,
        fixed_metadata=fixed_metadata,
        fixed_truth=tuple(float(v) for v in fixed_truth),
        n_fixed_days_used=n_present,
        n_fixed_days_dropped=n_dropped,
        applied_jump_dates=applied_jumps,
        f5_sha256=f5_sha256,
        variant=variant,
    )


# ---------------------------------------------------------------------------
# Multi-target driver (e.g. weekly batch)
# ---------------------------------------------------------------------------

def compute_for_targets(
    targets: Sequence[date],
    *,
    f5_root: Path = DEFAULT_F5_ROOT,
    fixed_station_id: str = DEFAULT_FIXED_STATION_ID,
    window_days: int = DEFAULT_WINDOW_DAYS,
    jumps: Sequence[FixedStationJump] | None = None,
    allow_partial_window: bool = False,
    min_fixed_days: int = DEFAULT_MIN_FIXED_DAYS,
    variant: str = "f5_1",
) -> tuple[pd.DataFrame, list[ComputeResult]]:
    """Run :func:`compute_for_target` for several dates.

    Returns ``(combined_df, per_target_results)``. ``combined_df`` is
    the per-(target_date, station) frame ready to write as Parquet.
    """
    results: list[ComputeResult] = []
    frames: list[pd.DataFrame] = []
    for t in targets:
        r = compute_for_target(
            t,
            f5_root=f5_root,
            fixed_station_id=fixed_station_id,
            window_days=window_days,
            jumps=jumps,
            allow_partial_window=allow_partial_window,
            min_fixed_days=min_fixed_days,
            variant=variant,
        )
        results.append(r)
        frames.append(r.df)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return combined, results


# ---------------------------------------------------------------------------
# Output: Parquet + provenance JSONL
# ---------------------------------------------------------------------------

def output_path_for_week(
    output_root: Path, year: int, iso_week: int, variant: str = "f5_1",
) -> Path:
    return output_root / variant / f"{year}" / f"W{iso_week:02d}.parquet"


def output_path_for_day(
    output_root: Path, target: date, variant: str = "f5_1",
) -> Path:
    return (
        output_root / variant / f"{target.year}" / f"{target.strftime('%Y%m%d')}.parquet"
    )


def write_parquet(df: pd.DataFrame, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(dest, index=False)
    return dest


def record_provenance(
    results: Sequence[ComputeResult],
    *,
    output_path: Path,
    provenance_path: Path | None = None,
    fixed_station_id: str,
    window_days: int,
) -> Path:
    """Append one JSONL record per target date that was computed."""
    import json
    out = provenance_path or DEFAULT_PROVENANCE_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    now_iso = datetime.now(UTC).isoformat()
    with out.open("a", encoding="utf-8") as f:
        for r in results:
            entry = {
                "target_date": str(r.df["target_date"].iloc[0]) if not r.df.empty else None,
                "variant": r.variant,
                "is_rapid": r.variant.startswith("r5"),
                "methodology_version": METHODOLOGY_VERSION,
                "filter_method": FILTER_METHOD,
                "fixed_station_id": fixed_station_id,
                "fixed_metadata": {
                    "rinex_id": r.fixed_metadata.rinex_id,
                    "frame": r.fixed_metadata.frame,
                    "ellipsoid": r.fixed_metadata.ellipsoid,
                },
                "window_days": window_days,
                "n_fixed_days_used": r.n_fixed_days_used,
                "n_fixed_days_dropped": r.n_fixed_days_dropped,
                "applied_jump_dates": [d.isoformat() for d in r.applied_jump_dates],
                "n_stations": len(r.df),
                "output_parquet": str(output_path),
                "f5_sha256": r.f5_sha256,
                "generated_at": now_iso,
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return out


__all__ = [
    "ComputeResult",
    "DEFAULT_FIXED_STATION_ID",
    "DEFAULT_F5_ROOT",
    "DEFAULT_JUMPS_PATH",
    "DEFAULT_MIN_FIXED_DAYS",
    "DEFAULT_OUTPUT_ROOT",
    "DEFAULT_PROVENANCE_PATH",
    "DEFAULT_WINDOW_DAYS",
    "FixedStationJump",
    "compute_for_target",
    "compute_for_targets",
    "load_jumps",
    "output_path_for_day",
    "output_path_for_week",
    "record_provenance",
    "write_parquet",
]
