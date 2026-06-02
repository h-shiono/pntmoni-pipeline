"""Common schema + aggregation + scraper entry points."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

# Common per-satellite row schema, populated by each constellation
# scraper. ``fetched_at`` is set at write time by ``write_snapshot``.
RowSchema = {
    "constellation":  "string",     # 'gps' | 'qzs' | 'gal'
    "satellite_id":   "string",     # convenience: 'G16', 'J194', 'E11'
    "svn":            "string",     # e.g. '56' (GPS), '002' (QZSS), 'GSAT0101' (Galileo)
    "prn":            "Int64",      # nullable int — 16, 194, 11
    "block":          "string",     # 'IIR', 'II-Q', '' …
    "slot":           "string",     # GPS plane/slot ('B1'), QZSS orbit ('QZO'), GAL slot
    "clock":          "string",     # 'RB' | 'PHM' | 'RAFS' …
    "status":         "string",     # 'operational' | 'outage' | 'decommissioned' | 'commissioning' | 'unusable'
    "signals":        "string",     # comma-joined: 'L1C/A, L1C, L2C, L5'
    "notice_id":      "string",     # active NAGU/NANU/NAQU number, '' if none
    "notice_type":    "string",     # 'FCSTSUMM' | 'GENERAL NOTICE' | ...
    "notice_subject": "string",     # human-readable summary
    "source_url":     "string",
}


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in RowSchema.items()})


def _http_get(url: str, *, timeout: float = 20.0) -> str:
    headers = {"User-Agent": "pntmoni-pipeline/0.1 (constellation_status fetcher)"}
    with httpx.Client(timeout=timeout, follow_redirects=True) as c:
        r = c.get(url, headers=headers)
        r.raise_for_status()
        return r.text


# --- Scraper entry points (thin wrappers around per-source modules) ---

def fetch_gps(*, http_get=_http_get) -> pd.DataFrame:
    from . import gps as _src
    return _src.parse(http_get(_src.URL))


def fetch_qzss(*, http_get=_http_get) -> pd.DataFrame:
    from . import qzss as _src
    return _src.parse(http_get(_src.URL))


def fetch_galileo(*, http_get=_http_get) -> pd.DataFrame:
    from . import galileo as _src
    return _src.parse(http_get(_src.URL))


@dataclass
class FetchResult:
    df: pd.DataFrame
    sources_ok: dict[str, bool] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


def fetch_all(*, http_get=_http_get) -> FetchResult:
    """Fetch GPS + QZSS + Galileo; missing sources are skipped (logged)."""
    frames: list[pd.DataFrame] = []
    sources_ok: dict[str, bool] = {}
    errors: dict[str, str] = {}
    for name, fn in (("gps", fetch_gps), ("qzs", fetch_qzss), ("gal", fetch_galileo)):
        try:
            d = fn(http_get=http_get)
            if len(d) == 0:
                raise RuntimeError("scraper returned 0 rows")
            frames.append(d)
            sources_ok[name] = True
            logger.info("constellation-status %s: %d satellites", name, len(d))
        except Exception as e:
            sources_ok[name] = False
            errors[name] = f"{type(e).__name__}: {e}"
            logger.warning("constellation-status %s failed: %s", name, errors[name])
    combined = pd.concat(frames, ignore_index=True) if frames else _empty_frame()
    return FetchResult(df=combined, sources_ok=sources_ok, errors=errors)


def write_snapshot(
    result: FetchResult,
    *,
    out_root: Path = Path("data/processed/constellation_status"),
    provenance_log: Path = Path("data/metadata/constellation_status.jsonl"),
) -> tuple[Path, Path]:
    """Write timestamped parquet + provenance JSONL entry.

    Layout:
      ``data/processed/constellation_status/YYYY/YYYY-MM-DD.parquet``
      ``data/processed/constellation_status/latest.parquet`` (overwritten)
    The "latest" copy is what the report driver reads by default.
    """
    now = datetime.now(UTC)
    df = result.df.copy()
    df["fetched_at"] = now
    out_root = Path(out_root)
    dated = out_root / f"{now.year}" / f"{now.strftime('%Y-%m-%d')}.parquet"
    dated.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(dated, index=False)
    latest = out_root / "latest.parquet"
    df.to_parquet(latest, index=False)

    provenance_log = Path(provenance_log)
    provenance_log.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "kind": "constellation_status",
        "fetched_at": now.isoformat(),
        "n_satellites": int(len(df)),
        "n_per_source": {k: int((df["constellation"] == k).sum()) for k in ("gps", "qzs", "gal")},
        "sources_ok": result.sources_ok,
        "errors": result.errors,
        "out_dated": str(dated),
        "out_latest": str(latest),
    }
    with provenance_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return dated, latest


# --- Shared helpers used by each scraper -----------------------------

def normalize_status(raw: str) -> str:
    """Map operator-specific wording → canonical status vocabulary."""
    if not raw:
        return "operational"
    low = raw.strip().lower()
    if "usable" in low and "not" not in low:
        return "operational"
    if "not usable" in low or "unusable" in low:
        return "unusable"
    if "decommission" in low or "removed" in low or "retired" in low:
        return "decommissioned"
    if "commission" in low:
        return "commissioning"
    if "outage" in low or "fcst" in low or "unavail" in low:
        return "outage"
    if low in ("o", "ok", "operational", "available"):
        return "operational"
    return low  # let unknowns through verbatim


def make_row(
    *, constellation: str, satellite_id: str, source_url: str,
    svn: str = "", prn: int | None = None, block: str = "",
    slot: str = "", clock: str = "",
    status: str = "operational", signals: Iterable[str] | str = (),
    notice_id: str = "", notice_type: str = "", notice_subject: str = "",
) -> dict[str, object]:
    if isinstance(signals, str):
        sig = signals
    else:
        sig = ", ".join(s for s in signals if s)
    return {
        "constellation":  constellation,
        "satellite_id":   satellite_id,
        "svn":            svn,
        "prn":            prn,
        "block":          block,
        "slot":           slot,
        "clock":          clock,
        "status":         status,
        "signals":        sig,
        "notice_id":      notice_id,
        "notice_type":    notice_type,
        "notice_subject": notice_subject,
        "source_url":     source_url,
    }


def rows_to_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    if not rows:
        return _empty_frame()
    df = pd.DataFrame(rows)
    # Enforce dtypes per RowSchema.
    for col, dt in RowSchema.items():
        if col not in df.columns:
            df[col] = pd.Series(dtype=dt)
        else:
            try:
                df[col] = df[col].astype(dt)
            except (TypeError, ValueError):
                df[col] = df[col].astype("string")
    return df[list(RowSchema.keys())]
