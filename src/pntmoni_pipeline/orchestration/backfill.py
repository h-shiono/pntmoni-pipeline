"""Backfill driver: run the daily chain over a date range.

Days run **sequentially** — each day already saturates the CPU via the
per-station thread pool in ``process``/``qc teqc``, so day-level
concurrency would only oversubscribe this (single, founder-owned)
machine. Resumability is free: ``run_day`` short-circuits days that are
already complete, and every per-unit step skips existing outputs.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterator

from .daily import DEFAULT_MODES, DayResult, run_day

logger = logging.getLogger(__name__)


def date_range(start: date, end: date) -> Iterator[date]:
    """Yield each calendar day in ``[start, end]`` inclusive."""
    if end < start:
        raise ValueError(f"end ({end}) is before start ({start})")
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


@dataclass
class BackfillResult:
    start: date
    end: date
    days: list[DayResult] = field(default_factory=list)

    def by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for d in self.days:
            counts[d.status] = counts.get(d.status, 0) + 1
        return counts

    @property
    def n_failed(self) -> int:
        return sum(1 for d in self.days if d.status == "failed")


def run_range(
    start: date,
    end: date,
    *,
    modes: tuple[str, ...] = DEFAULT_MODES,
    skip_acquire: bool = False,
    force: bool = False,
    workers: int | None = None,
    on_day: Callable[[DayResult], None] | None = None,
    **run_day_kwargs,
) -> BackfillResult:
    """Run ``run_day`` for every day in ``[start, end]``, continue-on-error."""
    result = BackfillResult(start=start, end=end)
    n_days = (end - start).days + 1
    for i, d in enumerate(date_range(start, end), start=1):
        logger.info("=== backfill %s (%d/%d) ===", d.isoformat(), i, n_days)
        t0 = time.monotonic()
        try:
            day = run_day(
                d,
                modes=modes,
                skip_acquire=skip_acquire,
                force=force,
                workers=workers,
                **run_day_kwargs,
            )
        except Exception as exc:  # noqa: BLE001 — a day must never abort the range
            logger.exception("day %s aborted hard", d)
            now = datetime.now(UTC)
            from ._steps import StepResult

            day = DayResult(
                target=d,
                steps=[StepResult("day", "failed", error=f"{type(exc).__name__}: {exc}")],
                status="failed",
                started_at=now,
                finished_at=now,
                wall_sec=time.monotonic() - t0,
            )
        result.days.append(day)
        if on_day is not None:
            on_day(day)
    return result
