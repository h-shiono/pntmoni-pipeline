"""Station qualification using a sliding-window of QC summaries.

Decides which GEONET stations qualify as the absolute-evaluation reference
set for a given ``ref_date``. Builds on a configurable rolling window of
``data/processed/qc_summary/{YYYY}/{YYYYMMDD}.parquet`` outputs and the
station registry (CLAS official evaluation points + out-of-service list).

Methodology (per Shiono & Kubo 2025, ION GNSS+ Table 2):

1. Pool every (station × day-in-window) sample for each
   (metric, 5°-elevation-bin) → derive a 99.73rd (or 0.27th, depending on
   "worse" direction) percentile threshold.
2. Per (station, day): an NG-day is any single excursion beyond a
   threshold across all (metric, bin) cells.
3. Per station: ``qc_pass = n_ng_days <= ng_days_max``. Default
   ``ng_days_max = ceil(n_days * 0.038)`` mirrors the legacy
   ``station_stats`` ratio (~2/52 weekly samples).
4. Overlay the CLAS official 72 evaluation points (force-include even
   when QC fails — protects coastal / island networks where no QC-pass
   station may exist).
5. Veto any station present in ``out_of_service.toml`` (hard exclude).

Final:

    qualified = (qc_pass OR force_eval) AND NOT out_of_service
"""
from __future__ import annotations

import logging
import math
import subprocess
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

# --- Methodology constants (paper Table 2) -------------------------------

MP_COMBINATIONS = ("MP12", "MP21", "MP15", "MP51")
SN_SIGNALS = ("SN1", "SN2", "SN5")
# Cycle-slip aggregation per the paper: sum across MP combinations + ION.
CS_PARTS = MP_COMBINATIONS + ("ION",)

# Elevation bins >= 15° (paper: "for all satellites observed above 15
# degrees"). Bin token format matches the qc_summary parquet columns
# (e.g. ``MP12_45_-_50_rms``).
ELEV_BINS = (
    "15_-_20", "20_-_25", "25_-_30", "30_-_35", "35_-_40",
    "40_-_45", "45_-_50", "50_-_55", "55_-_60", "60_-_65",
    "65_-_70", "70_-_75", "75_-_80", "80_-_85", "85_-_90",
)

DEFAULT_NG_RATIO = 0.038  # legacy: 2 NG / 52 weekly samples
METHODOLOGY_VERSION = "qual-v1"


@dataclass(frozen=True)
class Threshold:
    """One percentile threshold for a (metric, bin) cell."""

    metric: str
    bin: str  # "" for scalar (e.g. visibility)
    direction: str  # "upper" (worse when value > thr) or "lower" (worse when value < thr)
    value: float
    n_samples: int


@dataclass
class QualificationResult:
    ref_date: date
    window_days: int
    n_days_loaded: int
    ng_days_max: int
    thresholds: list[Threshold] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    force_eval_ids: set[str] = field(default_factory=set)
    out_of_service_ids: set[str] = field(default_factory=set)
    methodology_version: str = METHODOLOGY_VERSION
    pipeline_git_sha: str = ""
    generated_at: str = ""


# --- Registry loaders ---------------------------------------------------

def load_force_eval_ids(
    eval_periods_path: Path,
    ref_date: date,
) -> set[str]:
    """Return station IDs whose CLAS eval-period covers ``ref_date``.

    If no period covers ``ref_date`` (e.g. official report hasn't published
    the half yet), fall back to the LATEST period available — this matches
    operational reality: the most recent QSS report is treated as still
    authoritative until a newer one releases.
    """
    with eval_periods_path.open("rb") as f:
        data = tomllib.load(f)
    stations = data.get("stations", {})

    covered: set[str] = set()
    latest_end: date | None = None
    latest_ids: set[str] = set()
    for sid, info in stations.items():
        for p in info.get("periods", []):
            start = p["from"]
            end = p["to"]
            if isinstance(start, str):
                start = date.fromisoformat(start)
            if isinstance(end, str):
                end = date.fromisoformat(end)
            if start <= ref_date <= end:
                covered.add(sid)
            if latest_end is None or end > latest_end:
                latest_end = end
                latest_ids = {sid}
            elif end == latest_end:
                latest_ids.add(sid)

    if covered:
        logger.info(
            "force_eval: %d stations cover ref_date=%s",
            len(covered), ref_date.isoformat(),
        )
        return covered
    logger.warning(
        "force_eval: no period covers %s — falling back to latest period (end=%s, %d stations)",
        ref_date.isoformat(), latest_end, len(latest_ids),
    )
    return latest_ids


def load_out_of_service_ids(path: Path) -> set[str]:
    if not path.is_file():
        logger.warning("out_of_service.toml not found at %s — empty veto list", path)
        return set()
    with path.open("rb") as f:
        data = tomllib.load(f)
    return set(data.get("stations", {}).keys())


# --- Threshold derivation ------------------------------------------------

def _pool_metric_bin(
    tables: list[pa.Table],
    col: str,
) -> np.ndarray:
    arrays = []
    for t in tables:
        if col in t.column_names:
            arrays.append(np.asarray(t.column(col).to_pylist(), dtype=np.float64))
    if not arrays:
        return np.empty(0, dtype=np.float64)
    pooled = np.concatenate(arrays)
    return pooled[~np.isnan(pooled)]


def _percentile_index(values: np.ndarray, pct: float) -> float:
    """Sample percentile via sorted-index — matches legacy station_stats."""
    if values.size == 0:
        return float("nan")
    s = np.sort(values)
    idx = min(int(values.size * pct), values.size - 1)
    return float(s[idx])


def derive_thresholds(tables: list[pa.Table]) -> list[Threshold]:
    """Build the per-(metric, bin) 3-sigma threshold table."""
    out: list[Threshold] = []

    # Visibility (scalar, lower = worse)
    vis = _pool_metric_bin(tables, "visibility")
    if vis.size:
        # 0.27th percentile = legacy "i3sig = int(n * 0.9973)" on the
        # descending-sorted array, which is equivalent.
        s = np.sort(vis)[::-1]  # descending — worse is at the end
        idx = min(int(vis.size * 0.9973), vis.size - 1)
        out.append(Threshold("visibility", "", "lower", float(s[idx]), vis.size))

    # MP RMS (per combo × bin, upper = worse)
    for mp in MP_COMBINATIONS:
        for b in ELEV_BINS:
            col = f"{mp}_{b}_rms"
            vals = _pool_metric_bin(tables, col)
            thr = _percentile_index(vals, 0.9973) if vals.size else float("nan")
            out.append(Threshold(mp, b, "upper", thr, vals.size))

    # SN mean (per signal × bin, lower = worse)
    for sn in SN_SIGNALS:
        for b in ELEV_BINS:
            col = f"{sn}_{b}_mean"
            vals = _pool_metric_bin(tables, col)
            # Worse-end is the LOW tail; legacy used descending-sort + idx.
            if vals.size:
                s = np.sort(vals)[::-1]
                idx = min(int(vals.size * 0.9973), vals.size - 1)
                thr = float(s[idx])
            else:
                thr = float("nan")
            out.append(Threshold(sn, b, "lower", thr, vals.size))

    # CS aggregate (per bin, upper = worse)
    # Per-station-per-day CS-by-bin is the sum of MP_*_slps + ION_slps.
    # Pool: sum across each table's rows, then accumulate.
    for b in ELEV_BINS:
        per_day_sums: list[np.ndarray] = []
        for t in tables:
            cols = [f"{p}_{b}_slps" for p in CS_PARTS]
            present = [c for c in cols if c in t.column_names]
            if not present:
                continue
            arr = np.zeros(t.num_rows, dtype=np.float64)
            for c in present:
                arr = arr + np.nan_to_num(
                    np.asarray(t.column(c).to_pylist(), dtype=np.float64),
                    nan=0.0,
                )
            per_day_sums.append(arr)
        if per_day_sums:
            pooled = np.concatenate(per_day_sums)
            thr = _percentile_index(pooled, 0.9973)
        else:
            thr = float("nan")
        out.append(Threshold("CS", b, "upper", thr, int(sum(a.size for a in per_day_sums))))

    return out


# --- Per-(station, day) NG detection -----------------------------------

def _col_to_numpy(t: pa.Table, col: str) -> np.ndarray:
    """Return ``t[col]`` as a float64 array, or NaN-filled if absent."""
    if col not in t.column_names:
        return np.full(t.num_rows, np.nan, dtype=np.float64)
    return np.asarray(t.column(col).to_pylist(), dtype=np.float64)


def _ng_mask_for_day(
    t: pa.Table,
    thresholds: list[Threshold],
) -> np.ndarray:
    """Boolean array of length ``t.num_rows``: True if station has any excursion.

    Vectorised: each threshold contributes one numpy comparison; the
    resulting masks are OR-folded.
    """
    n = t.num_rows
    ng = np.zeros(n, dtype=bool)

    for thr in thresholds:
        if math.isnan(thr.value):
            continue

        if thr.metric == "visibility":
            v = _col_to_numpy(t, "visibility")
            ng |= np.where(np.isnan(v), False, v < thr.value)
            continue

        if thr.metric == "CS":
            total = np.zeros(n, dtype=np.float64)
            for part in CS_PARTS:
                v = _col_to_numpy(t, f"{part}_{thr.bin}_slps")
                total += np.nan_to_num(v, nan=0.0)
            ng |= total > thr.value
            continue

        if thr.metric.startswith("MP"):
            v = _col_to_numpy(t, f"{thr.metric}_{thr.bin}_rms")
            ng |= np.where(np.isnan(v), False, v > thr.value)
            continue

        if thr.metric.startswith("SN"):
            v = _col_to_numpy(t, f"{thr.metric}_{thr.bin}_mean")
            ng |= np.where(np.isnan(v), False, v < thr.value)
            continue

    return ng


def _first_excursion_reason(
    t: pa.Table,
    row_idx: int,
    thresholds: list[Threshold],
) -> str:
    """Slow per-row scan, only invoked when a station was already flagged NG."""
    for thr in thresholds:
        if math.isnan(thr.value):
            continue
        if thr.metric == "visibility":
            v_arr = _col_to_numpy(t, "visibility")
            v = v_arr[row_idx]
            if not math.isnan(v) and v < thr.value:
                return f"visibility ({v:.3f} < {thr.value:.3f})"
            continue
        if thr.metric == "CS":
            total = 0.0
            for part in CS_PARTS:
                v_arr = _col_to_numpy(t, f"{part}_{thr.bin}_slps")
                v = v_arr[row_idx]
                if not math.isnan(v):
                    total += v
            if total > thr.value:
                return f"CS@{thr.bin} ({total:.0f} > {thr.value:.0f})"
            continue
        if thr.metric.startswith("MP"):
            v_arr = _col_to_numpy(t, f"{thr.metric}_{thr.bin}_rms")
            v = v_arr[row_idx]
            if not math.isnan(v) and v > thr.value:
                return f"{thr.metric}@{thr.bin} ({v:.2f} > {thr.value:.2f})"
            continue
        if thr.metric.startswith("SN"):
            v_arr = _col_to_numpy(t, f"{thr.metric}_{thr.bin}_mean")
            v = v_arr[row_idx]
            if not math.isnan(v) and v < thr.value:
                return f"{thr.metric}@{thr.bin} ({v:.1f} < {thr.value:.1f})"
            continue
    return ""


# --- Window loading -----------------------------------------------------

def load_window_tables(
    qc_summary_root: Path,
    ref_date: date,
    window_days: int,
) -> tuple[list[pa.Table], list[date]]:
    """Load qc_summary parquets for ``[ref_date - window_days + 1, ref_date]``.

    Returns ``(tables, dates_actually_loaded)``; missing days are skipped
    (logged at WARNING).
    """
    tables: list[pa.Table] = []
    dates_loaded: list[date] = []
    for k in range(window_days):
        d = ref_date - timedelta(days=window_days - 1 - k)
        path = qc_summary_root / f"{d.year}" / f"{d.year:04d}{d.month:02d}{d.day:02d}.parquet"
        if not path.is_file():
            logger.warning("qc_summary missing for %s — skipping", d.isoformat())
            continue
        tables.append(pq.read_table(path))
        dates_loaded.append(d)
    return tables, dates_loaded


# --- Public entry point -------------------------------------------------

def qualify(
    ref_date: date,
    *,
    window_days: int = 90,
    ng_days_max: int | None = None,
    qc_summary_root: Path = Path("data/processed/qc_summary"),
    eval_periods_path: Path = Path("configs/stations/eval_periods.toml"),
    out_of_service_path: Path = Path("configs/stations/out_of_service.toml"),
    network_assignments_path: Path = Path("configs/stations/network_assignments.toml"),
) -> QualificationResult:
    tables, dates_loaded = load_window_tables(qc_summary_root, ref_date, window_days)
    if not tables:
        raise FileNotFoundError(
            f"no qc_summary parquets found for {ref_date - timedelta(days=window_days - 1)} .. {ref_date}"
        )

    n_days_loaded = len(tables)
    if ng_days_max is None:
        ng_days_max = math.ceil(n_days_loaded * DEFAULT_NG_RATIO)
    logger.info(
        "qualification: ref_date=%s window=%d days loaded=%d ng_days_max=%d",
        ref_date.isoformat(), window_days, n_days_loaded, ng_days_max,
    )

    thresholds = derive_thresholds(tables)
    n_thr = sum(1 for t in thresholds if not math.isnan(t.value))
    logger.info("thresholds: %d (metric, bin) cells derived", n_thr)

    force_eval_ids = load_force_eval_ids(eval_periods_path, ref_date)
    out_of_service_ids = load_out_of_service_ids(out_of_service_path)
    logger.info(
        "registry: force_eval=%d, out_of_service=%d",
        len(force_eval_ids), len(out_of_service_ids),
    )

    netid_lookup: dict[str, int] = {}
    if network_assignments_path.is_file():
        with network_assignments_path.open("rb") as f:
            na = tomllib.load(f)
        for sid, info in na.get("stations", {}).items():
            if "netid" in info:
                netid_lookup[sid] = int(info["netid"])

    # Tally NG-days per station across the loaded window.
    # Hot loop: vectorised NG-mask per day → accumulate counts.
    n_ng_days: dict[str, int] = {}
    n_seen: dict[str, int] = {}
    # Reason tracking: only for the first NG occurrence per station.
    first_reason: dict[str, str] = {}
    reason_pending: dict[str, tuple[pa.Table, int]] = {}
    for t in tables:
        ids = t.column("id").to_pylist()
        for sid in ids:
            n_seen[sid] = n_seen.get(sid, 0) + 1
        mask = _ng_mask_for_day(t, thresholds)
        ng_idx = np.flatnonzero(mask)
        for i in ng_idx:
            sid = ids[i]
            n_ng_days[sid] = n_ng_days.get(sid, 0) + 1
            if sid not in first_reason and sid not in reason_pending:
                reason_pending[sid] = (t, int(i))

    # Resolve reason strings (cheap, only for stations that ended up NG).
    for sid, (t, i) in reason_pending.items():
        first_reason[sid] = _first_excursion_reason(t, i, thresholds)

    all_stations = sorted(set(n_seen.keys()))
    rows: list[dict[str, Any]] = []
    for sid in all_stations:
        n_ng = n_ng_days.get(sid, 0)
        n_days_total = n_seen.get(sid, 0)
        qc_pass = n_ng <= ng_days_max
        force_eval = sid in force_eval_ids
        out_of_service = sid in out_of_service_ids
        qualified = (qc_pass or force_eval) and not out_of_service
        rows.append({
            "station": sid,
            "ref_date": ref_date.isoformat(),
            "window_days": window_days,
            "ng_days_max": ng_days_max,
            "n_days_total": n_days_total,
            "n_ng_days": n_ng,
            "qc_pass": qc_pass,
            "force_eval": force_eval,
            "out_of_service": out_of_service,
            "qualified": qualified,
            "netid": netid_lookup.get(sid),
            "reason_first_excursion": first_reason.get(sid, ""),
        })

    n_qual = sum(1 for r in rows if r["qualified"])
    logger.info(
        "qualification done: %d/%d stations qualified (qc_pass=%d, force_eval=%d, out_of_service=%d)",
        n_qual, len(rows),
        sum(1 for r in rows if r["qc_pass"]),
        len(force_eval_ids),
        len(out_of_service_ids),
    )

    return QualificationResult(
        ref_date=ref_date,
        window_days=window_days,
        n_days_loaded=n_days_loaded,
        ng_days_max=ng_days_max,
        thresholds=thresholds,
        rows=rows,
        force_eval_ids=force_eval_ids,
        out_of_service_ids=out_of_service_ids,
        pipeline_git_sha=_git_sha(),
        generated_at=datetime.now(UTC).isoformat(),
    )


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


# --- Output -------------------------------------------------------------

def write_parquet(result: QualificationResult, dest: Path) -> Path:
    """Write the per-station qualification table to ``dest``."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(result.rows)
    # Attach provenance to the table's schema metadata.
    md = {
        b"methodology_version": result.methodology_version.encode(),
        b"pipeline_git_sha": result.pipeline_git_sha.encode(),
        b"ref_date": result.ref_date.isoformat().encode(),
        b"window_days": str(result.window_days).encode(),
        b"n_days_loaded": str(result.n_days_loaded).encode(),
        b"ng_days_max": str(result.ng_days_max).encode(),
        b"force_eval_n": str(len(result.force_eval_ids)).encode(),
        b"out_of_service_n": str(len(result.out_of_service_ids)).encode(),
        b"generated_at": result.generated_at.encode(),
    }
    table = table.replace_schema_metadata(md)
    pq.write_table(table, dest)
    logger.info("wrote %s (%d rows)", dest, table.num_rows)
    return dest


def write_provenance_jsonl(result: QualificationResult, dest: Path) -> Path:
    """Append a per-run record with full threshold table.

    The thresholds are recorded inline so a future audit can reproduce any
    decision without re-loading qc_summaries.
    """
    import json
    dest.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ref_date": result.ref_date.isoformat(),
        "window_days": result.window_days,
        "n_days_loaded": result.n_days_loaded,
        "ng_days_max": result.ng_days_max,
        "methodology_version": result.methodology_version,
        "pipeline_git_sha": result.pipeline_git_sha,
        "generated_at": result.generated_at,
        "force_eval_n": len(result.force_eval_ids),
        "out_of_service_n": len(result.out_of_service_ids),
        "force_eval_ids": sorted(result.force_eval_ids),
        "out_of_service_ids": sorted(result.out_of_service_ids),
        "thresholds": [
            {
                "metric": t.metric,
                "bin": t.bin,
                "direction": t.direction,
                "value": t.value,
                "n_samples": t.n_samples,
            }
            for t in result.thresholds
        ],
        "summary": {
            "n_stations": len(result.rows),
            "n_qualified": sum(1 for r in result.rows if r["qualified"]),
            "n_qc_pass": sum(1 for r in result.rows if r["qc_pass"]),
        },
    }
    with dest.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    logger.info("appended provenance to %s", dest)
    return dest
