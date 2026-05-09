"""Per-DOY processing run summary (Tier 1 log + Tier 2 JSONL).

The summary aggregates per-station ``ProcessingResult`` durations into
a small record that is both:

- printed/logged at end of ``process_doy`` (Tier 1: immediate feel for
  how long a 1300-station DOY takes), and
- appended to ``data/metadata/processing.jsonl`` (Tier 2: trend
  baseline, e.g. for noticing silent regressions after CLASLIB rebases
  or MOD-NNN modifications per ADR 0004).

Per-station ProcessingResult records remain in-memory only; we do not
persist them in Phase 0. If fine-grained analysis is ever required,
the same JSONL pattern can be repeated at the result level.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ._base import ProcessingResult

logger = logging.getLogger(__name__)

DEFAULT_STATS_PATH = Path("data/metadata/processing.jsonl")


@dataclass(frozen=True)
class RunSummary:
    engine: str
    engine_version: str
    mode: str
    date: str                       # ISO YYYY-MM-DD
    started_at: datetime
    finished_at: datetime
    wall_sec: float                 # wall-clock duration of process_doy
    n_stations: int                 # total stations attempted
    n_succeeded: int                # ran rnx2rtkp to completion this run
    n_skipped: int                  # output already existed (skip path)
    n_failed: int                   # raised an exception
    duration_total_sec: float       # Σ per-station durations (≈ CPU time)
    duration_p50_sec: float
    duration_p95_sec: float
    failed_stations: list[str] = field(default_factory=list)

    def to_jsonable(self) -> dict[str, Any]:
        d = asdict(self)
        d["started_at"] = self.started_at.isoformat()
        d["finished_at"] = self.finished_at.isoformat()
        return d


def percentile(values: Iterable[float], p: float) -> float:
    """Linear-interpolated percentile (``p`` in [0, 100]).

    Returns ``0.0`` for an empty input — keeps callers free of guards.
    """
    s = sorted(values)
    if not s:
        return 0.0
    if p <= 0:
        return s[0]
    if p >= 100:
        return s[-1]
    k = (len(s) - 1) * p / 100
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def summarize(
    results: list[ProcessingResult],
    *,
    failed_stations: list[str],
    started_at: datetime,
    finished_at: datetime,
    engine: str,
    engine_version: str,
    mode: str,
    date_iso: str,
) -> RunSummary:
    """Aggregate ProcessingResults + failures into a RunSummary."""
    succeeded = [r for r in results if not r.skipped]
    skipped = [r for r in results if r.skipped]
    durations = [r.duration_sec for r in succeeded]
    return RunSummary(
        engine=engine,
        engine_version=engine_version,
        mode=mode,
        date=date_iso,
        started_at=started_at,
        finished_at=finished_at,
        wall_sec=(finished_at - started_at).total_seconds(),
        n_stations=len(results) + len(failed_stations),
        n_succeeded=len(succeeded),
        n_skipped=len(skipped),
        n_failed=len(failed_stations),
        duration_total_sec=sum(durations),
        duration_p50_sec=percentile(durations, 50),
        duration_p95_sec=percentile(durations, 95),
        failed_stations=list(failed_stations),
    )


def record(summary: RunSummary, path: Path | None = None) -> Path:
    """Append one ``RunSummary`` as a JSON line."""
    out = path or DEFAULT_STATS_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary.to_jsonable(), ensure_ascii=False) + "\n")
    return out


def format_summary(s: RunSummary) -> str:
    """Multi-line human-readable summary for terminal/log output."""
    failed_preview = ""
    if s.failed_stations:
        head = ", ".join(s.failed_stations[:5])
        more = f" (+{len(s.failed_stations) - 5} more)" if len(s.failed_stations) > 5 else ""
        failed_preview = f" [{head}{more}]"
    lines = [
        f"Processed {s.n_stations} station(s) for {s.date} "
        f"(mode={s.mode}, engine={s.engine} {s.engine_version})",
        f"  succeeded : {s.n_succeeded}",
        f"  skipped   : {s.n_skipped}",
        f"  failed    : {s.n_failed}{failed_preview}",
        f"Wall time   : {s.wall_sec:.1f} s ({s.wall_sec / 60:.2f} min)",
        f"Per-station : p50={s.duration_p50_sec:.1f}s "
        f"p95={s.duration_p95_sec:.1f}s "
        f"total={s.duration_total_sec / 60:.1f} min",
    ]
    if s.n_succeeded and s.wall_sec > 0:
        speedup = s.duration_total_sec / s.wall_sec
        lines.append(f"Parallelism : {speedup:.1f}x (Σ duration / wall)")
    return "\n".join(lines)


__all__ = [
    "DEFAULT_STATS_PATH",
    "RunSummary",
    "format_summary",
    "percentile",
    "record",
    "summarize",
]
