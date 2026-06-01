"""L6 broadcast Alert-flag extraction & aggregation (methodology §6).

The CLAS L6 CSSR Data Part carries a per-message **Alert flag**. We
extract it via the ``pntmoni-claslib`` ``ssr2osr -dump`` utility, which
writes ``parse_cssr_header.csv`` with columns::

    Epoch Time, Preamble, PRN, L6 message type ID, Vender ID,
    Message Generation Facility ID and CLAS Transmit Pattern ID,
    CLAS Transmit Pattern ID, Subframe indicator, Alert Flag

``Epoch Time`` is the GPS time-of-week (seconds); ``Alert Flag`` is
0/1 per L6 message. This module runs the dump per daily L6 file,
parses the header CSV, and aggregates the alert flag (counts, per-PRN
breakdown, time series), optionally cross-referencing official
satellite-outage notices (NAGU/NANU/NAQU) by PRN × time.

The subprocess wrapper (:func:`run_dump`) is separated from the pure
parse/aggregate functions so the latter are unit-testable without the
binary.
"""
from __future__ import annotations

import calendar
import logging
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from ..acquisition._base import sha256_file

logger = logging.getLogger(__name__)

# ssr2osr built locally (see processing/_binary.py for the rnx2rtkp
# analogue). Kept as a build artifact, out of git.
DEFAULT_SSR2OSR_CANDIDATES = (
    Path("vendor/pntmoni-claslib/util/ssr2osr/ssr2osr"),
    Path("vendor/claslib/util/ssr2osr/ssr2osr"),
)
DEFAULT_GRID = Path("configs/aux_data/clas_grid.def")

# GPS epoch and the GPST→UTC offset. The offset is the (leap_seconds −
# 19) difference; it has been 18 s since 2017-01-01. The v1.0.0
# evaluation period is 2025-04 onward, so 18 is correct throughout;
# revisit if backfill crosses a leap-second boundary (< 2017).
GPS_EPOCH = datetime(1980, 1, 6, tzinfo=UTC)
GPST_UTC_OFFSET_SEC = 18

# parse_cssr_header.csv column order (ssr2osr cssr.c:4352).
RAW_COLUMNS = (
    "tow", "preamble", "prn", "msg_type_id", "vender_id",
    "mgf_pattern", "pattern", "subframe_indicator", "alert_flag",
)


def find_binary(candidates: Sequence[Path] = DEFAULT_SSR2OSR_CANDIDATES) -> Path:
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(
        "ssr2osr binary not found. Build it (macOS/Linux):\n"
        "  cd vendor/pntmoni-claslib/util/ssr2osr && make\n"
        f"  (looked in: {', '.join(str(c) for c in candidates)})"
    )


# --- GPS time -----------------------------------------------------------

def tow_to_utc(tow: float, target_date: date) -> datetime:
    """Map a GPS time-of-week to a UTC datetime, anchored to ``target_date``.

    The header CSV records only the time-of-week, so the GPS week is
    inferred from ``target_date``. The result is snapped to within
    ±half a week of ``target_date`` to resolve a Saturday→Sunday week
    rollover inside a single daily file.
    """
    days = (target_date - GPS_EPOCH.date()).days
    week = days // 7
    gpst = GPS_EPOCH + timedelta(weeks=week, seconds=float(tow))
    # Resolve week rollover: keep gpst within ±3.5 days of the target.
    while gpst - datetime.combine(target_date, datetime.min.time(), UTC) > timedelta(days=3.5):
        gpst -= timedelta(weeks=1)
    while datetime.combine(target_date, datetime.min.time(), UTC) - gpst > timedelta(days=3.5):
        gpst += timedelta(weeks=1)
    return gpst - timedelta(seconds=GPST_UTC_OFFSET_SEC)


# --- ssr2osr -dump wrapper ----------------------------------------------

def run_dump(
    l6_path: Path,
    *,
    grid_path: Path = DEFAULT_GRID,
    binary: Path | None = None,
    workdir: Path | None = None,
    timeout: int = 600,
) -> Path:
    """Run ``ssr2osr -dump`` on ``l6_path``; return the header CSV path.

    ``ssr2osr`` writes ``parse_cssr_*.csv`` into its working directory,
    so a dedicated ``workdir`` is used. A minimal config supplies the
    CSSR grid file (required, else the decode aborts).
    """
    binary = (binary or find_binary()).resolve()
    grid_path = grid_path.resolve()
    if not grid_path.is_file():
        raise FileNotFoundError(f"CSSR grid file not found: {grid_path}")
    work = workdir or Path(tempfile.mkdtemp(prefix="l6dump_"))
    work.mkdir(parents=True, exist_ok=True)
    conf = work / "dump.conf"
    conf.write_text(f"file-cssrgridfile  ={grid_path}\n", encoding="utf-8")

    cmd = [str(binary), "-k", str(conf), "-dump", str(l6_path.resolve())]
    logger.info("ssr2osr -dump: %s", l6_path.name)
    proc = subprocess.run(
        cmd, cwd=work, capture_output=True, text=True, check=False, timeout=timeout,
    )
    header = work / "parse_cssr_header.csv"
    if not header.is_file():
        raise RuntimeError(
            f"ssr2osr -dump produced no parse_cssr_header.csv "
            f"(rc={proc.returncode}). stderr:\n{proc.stderr[-2000:]}"
        )
    return header


# --- Parse / aggregate (pure) -------------------------------------------

def parse_header_csv(path: Path) -> pd.DataFrame:
    """Parse ``parse_cssr_header.csv`` into a normalized DataFrame."""
    df = pd.read_csv(path, skipinitialspace=True)
    if len(df.columns) != len(RAW_COLUMNS):
        raise ValueError(
            f"{path}: expected {len(RAW_COLUMNS)} columns, got {len(df.columns)}: "
            f"{list(df.columns)}"
        )
    df.columns = list(RAW_COLUMNS)
    df["tow"] = df["tow"].astype("int64")
    df["prn"] = df["prn"].astype("int64")
    df["alert_flag"] = df["alert_flag"].astype("int64")
    return df


def dedup_messages(df: pd.DataFrame) -> pd.DataFrame:
    """Drop duplicate L6 messages sharing the same ``(tow, prn)``.

    Within one daily file each (epoch, satellite) carries a single L6
    message, so duplicates can only arise from overlapping hourly-file
    concatenation or an accidental re-dump; those are dropped (kept
    once). Distinct PRNs at the same epoch (multiple satellites) are
    **not** duplicates and are preserved. Dedup is intended per file
    (per day): ``tow`` is a seconds-of-week value that legitimately
    recurs every week, so it must never be deduped across days.
    """
    deduped = df.drop_duplicates(subset=["tow", "prn"], keep="first")
    n = len(df) - len(deduped)
    if n:
        logger.warning("dropped %d duplicate (tow, prn) L6 message(s)", n)
    return deduped.reset_index(drop=True)


def file_events(path: Path, target_date: date) -> pd.DataFrame:
    """Per-alert rows (alert_flag == 1) for one daily header CSV.

    Returns columns ``date, prn, tow, time_utc`` (one row per alerting
    L6 message). Duplicate ``(tow, prn)`` messages are dropped first.
    Empty frame if no alerts.
    """
    df = dedup_messages(parse_header_csv(path))
    alerts = df[df["alert_flag"] == 1].copy()
    if alerts.empty:
        return pd.DataFrame(columns=["date", "prn", "tow", "time_utc"])
    alerts["date"] = target_date.isoformat()
    alerts["time_utc"] = alerts["tow"].map(lambda t: tow_to_utc(t, target_date))
    return alerts[["date", "prn", "tow", "time_utc"]].reset_index(drop=True)


@dataclass
class AlertSummary:
    period: str                       # "YYYY-MM" or a date
    n_messages: int                   # total L6 messages parsed
    n_alerts: int                     # messages with alert_flag == 1
    alert_rate: float                 # n_alerts / n_messages
    per_prn: dict[int, int]           # prn -> alert count
    events: pd.DataFrame = field(default_factory=pd.DataFrame)  # date,prn,tow,time_utc
    n_duplicates: int = 0             # duplicate (tow, prn) messages dropped


def summarize(
    per_file: Sequence[tuple[Path, date]],
    *,
    period: str,
) -> AlertSummary:
    """Aggregate alerts across daily (header_csv, date) pairs.

    Each file is deduplicated on ``(tow, prn)`` before counting (see
    :func:`dedup_messages`); ``n_messages`` and ``n_alerts`` are over
    the unique messages.
    """
    n_messages = 0
    n_duplicates = 0
    event_frames: list[pd.DataFrame] = []
    for path, d in per_file:
        raw = parse_header_csv(path)
        df = dedup_messages(raw)
        n_duplicates += len(raw) - len(df)
        n_messages += len(df)
        al = df[df["alert_flag"] == 1]
        if not al.empty:
            ev = al[["prn", "tow"]].copy()
            ev["date"] = d.isoformat()
            ev["time_utc"] = ev["tow"].map(lambda t: tow_to_utc(t, d))
            event_frames.append(ev[["date", "prn", "tow", "time_utc"]])
    events = (
        pd.concat(event_frames, ignore_index=True)
        if event_frames else pd.DataFrame(columns=["date", "prn", "tow", "time_utc"])
    )
    n_alerts = len(events)
    per_prn = (
        events.groupby("prn").size().astype(int).to_dict() if n_alerts else {}
    )
    return AlertSummary(
        period=period,
        n_messages=n_messages,
        n_alerts=n_alerts,
        alert_rate=(n_alerts / n_messages) if n_messages else 0.0,
        per_prn={int(k): int(v) for k, v in per_prn.items()},
        events=events,
        n_duplicates=n_duplicates,
    )


def cross_reference_outages(
    events: pd.DataFrame,
    outages: pd.DataFrame,
) -> pd.DataFrame:
    """Annotate each alert event with a matching outage notice, if any.

    Matches when the alert ``prn`` equals an outage ``prn`` and the
    alert ``time_utc`` falls within ``[start_at, end_at]`` (open
    end_at = ongoing). Adds an ``outage_match`` column (notice id or
    NaN). ``outages`` must have ``prn``, ``start_at``, ``end_at`` (and
    ideally an id column); missing → events returned unchanged.
    """
    if events.empty or outages.empty or "prn" not in outages.columns:
        events = events.copy()
        events["outage_match"] = pd.NA
        return events
    id_col = next((c for c in ("event_id", "id", "reference", "root") if c in outages.columns), None)
    out = events.copy()
    matches: list[object] = []
    for _, ev in out.iterrows():
        cand = outages[outages["prn"] == ev["prn"]]
        hit = pd.NA
        for _, o in cand.iterrows():
            start = o.get("start_at")
            end = o.get("end_at")
            if start is not None and ev["time_utc"] >= start and (
                end is None or pd.isna(end) or ev["time_utc"] <= end
            ):
                hit = o[id_col] if id_col else True
                break
        matches.append(hit)
    out["outage_match"] = matches
    return out


# --- Output -------------------------------------------------------------

def write_parquet(summary: AlertSummary, dest: Path) -> Path:
    """Write the per-alert events parquet (one row per alerting message)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    summary.events.to_parquet(dest, index=False)
    logger.info("wrote %s (%d alert events)", dest, len(summary.events))
    return dest


def write_provenance_jsonl(
    summary: AlertSummary,
    dest: Path,
    *,
    ssr2osr_version: str,
    inputs_sha256: dict[str, str],
) -> Path:
    import json
    dest.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "period": summary.period,
        "n_messages": summary.n_messages,
        "n_alerts": summary.n_alerts,
        "alert_rate": summary.alert_rate,
        "n_duplicates": summary.n_duplicates,
        "per_prn": summary.per_prn,
        "ssr2osr_version": ssr2osr_version,
        "inputs_sha256": inputs_sha256,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    with dest.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    logger.info("appended L6-alert provenance to %s", dest)
    return dest


# --- Monthly orchestration ----------------------------------------------

DEFAULT_L6_ROOT = Path("data/raw/l6")
DEFAULT_OUT_ROOT = Path("data/processed/l6_alerts")
DEFAULT_PROVENANCE = Path("data/metadata/l6_alerts.jsonl")


def merged_l6_path(l6_root: Path, target: date) -> Path:
    """Path of the day's concatenated L6 file (see ``acquisition.qzss_l6``)."""
    doy = int(target.strftime("%j"))
    return l6_root / f"{target.year}" / f"{doy:03d}" / f"{target.year}{doy:03d}AX.l6"


def process_month(
    year: int,
    month: int,
    *,
    l6_root: Path = DEFAULT_L6_ROOT,
    grid_path: Path = DEFAULT_GRID,
    binary: Path | None = None,
    outages_path: Path | None = None,
    out_root: Path = DEFAULT_OUT_ROOT,
    provenance_log: Path = DEFAULT_PROVENANCE,
    ssr2osr_version: str = "pntmoni-claslib ssr2osr",
) -> tuple[AlertSummary, Path]:
    """Dump + aggregate L6 alerts for every available day in the month.

    Missing daily L6 files are skipped (logged). Writes the per-alert
    events parquet and appends a provenance record. Returns
    ``(summary, parquet_path)``.
    """
    binary = (binary or find_binary()).resolve()
    period = f"{year}-{month:02d}"
    days = [date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]

    tmp = Path(tempfile.mkdtemp(prefix="l6dump_month_"))
    per_file: list[tuple[Path, date]] = []
    inputs_sha256: dict[str, str] = {}
    for d in days:
        l6 = merged_l6_path(l6_root, d)
        if not l6.is_file():
            logger.warning("L6 missing for %s — skipping", d.isoformat())
            continue
        header = run_dump(
            l6, grid_path=grid_path, binary=binary, workdir=tmp / d.strftime("%Y%m%d"),
        )
        per_file.append((header, d))
        inputs_sha256[l6.name] = sha256_file(l6)

    if not per_file:
        raise FileNotFoundError(f"no L6 files for {period} under {l6_root}")

    summary = summarize(per_file, period=period)

    if outages_path is not None and Path(outages_path).is_file() and not summary.events.empty:
        outages = pd.read_parquet(outages_path)
        summary.events = cross_reference_outages(summary.events, outages)
        logger.info("cross-referenced %d alert events against %s", len(summary.events), outages_path)

    dest = out_root / f"{year}" / f"{period}.parquet"
    write_parquet(summary, dest)
    write_provenance_jsonl(
        summary, provenance_log,
        ssr2osr_version=ssr2osr_version, inputs_sha256=inputs_sha256,
    )
    logger.info(
        "L6 alerts %s: %d alerts / %d messages (rate=%.4g) across %d day(s)",
        period, summary.n_alerts, summary.n_messages, summary.alert_rate, len(per_file),
    )
    return summary, dest


__all__ = [
    "AlertSummary",
    "DEFAULT_GRID",
    "DEFAULT_L6_ROOT",
    "DEFAULT_OUT_ROOT",
    "DEFAULT_PROVENANCE",
    "cross_reference_outages",
    "file_events",
    "find_binary",
    "merged_l6_path",
    "parse_header_csv",
    "process_month",
    "run_dump",
    "summarize",
    "tow_to_utc",
    "write_parquet",
    "write_provenance_jsonl",
]
