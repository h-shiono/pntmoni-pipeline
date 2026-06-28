"""Nightly catchup: always run the current day, then backfill N gap days.

Steady-state operation. Each invocation:

  1. Runs `daily` for ``today - lag_days`` (keep current — always).
  2. Scans ``[backfill_start, target-1]`` for days that are not yet
     complete (``is_day_complete``), orders them, and runs up to
     ``backfill_days`` of them (catch up history with spare capacity).

Gap detection uses ``is_day_complete`` rather than a stored cursor, so it
is self-healing: a previously partial/failed day is naturally re-targeted,
and the job is idempotent (already-complete days are never re-run).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

from .daily import DEFAULT_MODES, DayResult, is_day_complete, run_day

logger = logging.getLogger(__name__)

DEFAULT_BACKFILL_START = date(2026, 1, 1)
DEFAULT_BACKFILL_DAYS = 2
# today-4: CLASLIB needs the target day's BRDC *and* the next day's. CDDIS
# publishes BRDC with latency, so a 2-day lag often 404s on the next-day BRDC
# (today-1) at 03:00 and the daily partials. 4 days keeps the needed BRDC
# (today-3) reliably published.
DEFAULT_LAG_DAYS = 4


@dataclass
class CatchupResult:
    today: date
    target: date
    daily: DayResult
    backfill: list[DayResult] = field(default_factory=list)
    gaps_total: int = 0  # incomplete days found in the window (before capping to N)

    @property
    def gaps_remaining(self) -> int:
        return max(0, self.gaps_total - len(self.backfill))


def find_gaps(
    start: date,
    end: date,
    *,
    modes: tuple[str, ...] = DEFAULT_MODES,
    order: str = "newest",
) -> list[date]:
    """Return the days in ``[start, end]`` that are not yet complete."""
    gaps: list[date] = []
    d = start
    while d <= end:
        if not is_day_complete(d, modes=modes):
            gaps.append(d)
        d += timedelta(days=1)
    if order == "newest":
        gaps.reverse()
    elif order != "oldest":
        raise ValueError(f"order must be 'newest' or 'oldest', got {order!r}")
    return gaps


def run_catchup(
    today: date,
    *,
    lag_days: int = DEFAULT_LAG_DAYS,
    backfill_start: date = DEFAULT_BACKFILL_START,
    backfill_days: int = DEFAULT_BACKFILL_DAYS,
    order: str = "newest",
    modes: tuple[str, ...] = DEFAULT_MODES,
    max_hours: float | None = None,
    workers: int | None = None,
    **run_day_kwargs,
) -> CatchupResult:
    """Run the current day's daily, then up to ``backfill_days`` gap days."""
    t0 = time.monotonic()
    target = today - timedelta(days=lag_days)

    # 1. The daily — always runs first.
    logger.info("catchup: daily target = %s", target.isoformat())
    daily = run_day(target, modes=modes, workers=workers, **run_day_kwargs)

    # 2. Backfill gaps in [backfill_start, target - 1].
    result = CatchupResult(today=today, target=target, daily=daily)
    end = target - timedelta(days=1)
    if end < backfill_start:
        logger.info("catchup: no backfill window yet (start %s > end %s)",
                    backfill_start.isoformat(), end.isoformat())
        return result

    gaps = find_gaps(backfill_start, end, modes=modes, order=order)
    result.gaps_total = len(gaps)
    logger.info(
        "catchup: %d incomplete day(s) in %s..%s; backfilling up to %d (%s-first)",
        len(gaps), backfill_start.isoformat(), end.isoformat(), backfill_days, order,
    )

    for d in gaps[:backfill_days]:
        if max_hours is not None and (time.monotonic() - t0) / 3600.0 >= max_hours:
            logger.info("catchup: max_hours=%.1f reached; stopping backfill early", max_hours)
            break
        result.backfill.append(
            run_day(d, modes=modes, workers=workers, **run_day_kwargs)
        )

    done = sum(1 for r in result.backfill if r.status == "ok")
    logger.info(
        "catchup done: daily=%s, backfill %d/%d ok, %d gap(s) remaining",
        daily.status, done, len(result.backfill), result.gaps_remaining,
    )
    return result
