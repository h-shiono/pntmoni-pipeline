"""Top-level ``daily`` and ``backfill`` orchestration commands."""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from ..orchestration import DEFAULT_MODES, DayResult, run_day, run_range
from ..orchestration._notify import notify

logger = logging.getLogger(__name__)

DEFAULT_LOG_DIR = Path("data/logs")


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError as e:
        raise typer.BadParameter(f"date must be YYYY-MM-DD: {e}") from e


def _resolve_modes(modes: list[str] | None) -> tuple[str, ...]:
    return tuple(modes) if modes else DEFAULT_MODES


def _add_log_file(stem: str) -> Path:
    """Attach a per-run file handler under data/logs and return its path."""
    DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = DEFAULT_LOG_DIR / f"{stem}_{ts}.log"
    handler = logging.FileHandler(path)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s — %(message)s")
    )
    logging.getLogger().addHandler(handler)
    return path


def _step_line(d: DayResult) -> str:
    parts = [f"{s.name}={s.status}" for s in d.steps]
    return f"  {d.target.isoformat()} [{d.status}] " + " ".join(parts)


def daily(
    date_: Annotated[
        str | None,
        typer.Option("--date", "-d", help="Target date (YYYY-MM-DD). Default: today − lag."),
    ] = None,
    lag_days: Annotated[
        int,
        typer.Option("--lag-days", help="When --date omitted, process today − lag (data latency)."),
    ] = 2,
    modes: Annotated[
        list[str] | None,
        typer.Option("--mode", "-m", help="Config mode; repeat. Default: verify + ttff_verify."),
    ] = None,
    skip_acquire: Annotated[
        bool, typer.Option("--skip-acquire", help="Assume RINEX/BRDC/L6 already present."),
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Re-run processing/QC even if outputs exist."),
    ] = False,
    workers: Annotated[
        int | None, typer.Option("--workers", "-j", help="Per-station thread pool size."),
    ] = None,
) -> None:
    """Run the full per-DOY chain (acquire → process → QC) for one day."""
    target = _parse_date(date_) if date_ else date.today() - timedelta(days=lag_days)
    log_path = _add_log_file("daily")
    logger.info("daily run for %s (log: %s)", target.isoformat(), log_path)

    result = run_day(
        target,
        modes=_resolve_modes(modes),
        skip_acquire=skip_acquire,
        force=force,
        workers=workers,
    )

    typer.echo(_step_line(result))
    if result.status != "ok":
        notify(
            f"pntmoni daily {target.isoformat()}: {result.status}",
            _step_line(result).strip(),
            priority="high" if result.status == "failed" else "default",
        )
        raise typer.Exit(code=1 if result.status == "failed" else 0)


def backfill(
    start: Annotated[str, typer.Option("--start", help="First date (YYYY-MM-DD), inclusive.")],
    end: Annotated[str, typer.Option("--end", help="Last date (YYYY-MM-DD), inclusive.")],
    modes: Annotated[
        list[str] | None,
        typer.Option("--mode", "-m", help="Config mode; repeat. Default: verify + ttff_verify."),
    ] = None,
    skip_acquire: Annotated[
        bool, typer.Option("--skip-acquire", help="Assume RINEX/BRDC/L6 already present."),
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Re-run processing/QC even if outputs exist."),
    ] = False,
    workers: Annotated[
        int | None, typer.Option("--workers", "-j", help="Per-station thread pool size."),
    ] = None,
) -> None:
    """Run the daily chain over a date range (sequential, resumable)."""
    start_d = _parse_date(start)
    end_d = _parse_date(end)
    if end_d < start_d:
        raise typer.BadParameter("--end is before --start")
    log_path = _add_log_file("backfill")
    n_days = (end_d - start_d).days + 1
    logger.info(
        "backfill %s..%s (%d days, log: %s)",
        start_d.isoformat(), end_d.isoformat(), n_days, log_path,
    )

    result = run_range(
        start_d,
        end_d,
        modes=_resolve_modes(modes),
        skip_acquire=skip_acquire,
        force=force,
        workers=workers,
        on_day=lambda d: typer.echo(_step_line(d)),
    )

    counts = result.by_status()
    summary = "  ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    typer.echo(f"\nbackfill {start_d}..{end_d}: {summary}")
    if result.n_failed:
        failed_days = ", ".join(d.target.isoformat() for d in result.days if d.status == "failed")
        notify(
            f"pntmoni backfill {start_d}..{end_d}: {result.n_failed} failed",
            f"failed days: {failed_days}",
            priority="high",
        )
        raise typer.Exit(code=1)
