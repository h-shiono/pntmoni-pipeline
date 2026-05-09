"""``pntmoni-pipeline analyze ...`` subcommands."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated

import typer

from ..analysis import _accuracy_stats, _epoch_errors, _reference_coords, _ttff, format_summary

app = typer.Typer(no_args_is_help=True)

logger = logging.getLogger(__name__)


def _parse_iso_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError as e:
        raise typer.BadParameter(f"date must be YYYY-MM-DD: {e}") from e


def _parse_iso_week(s: str) -> tuple[int, int]:
    """Accept ``YYYY-Www`` (ISO 8601). Returns ``(year, week)``."""
    try:
        year_s, week_s = s.split("-W")
        return int(year_s), int(week_s)
    except (ValueError, AttributeError) as e:
        raise typer.BadParameter(f"week must be YYYY-Www (ISO 8601): {e}") from e


def _iso_week_dates(year: int, iso_week: int) -> list[date]:
    """All seven dates of a given ISO 8601 calendar week."""
    monday = date.fromisocalendar(year, iso_week, 1)
    return [monday + timedelta(days=i) for i in range(7)]


@app.command("ttff")
def cmd_ttff(
    date_: Annotated[
        str, typer.Option("--date", "-d", help="Target date (YYYY-MM-DD).")
    ],
    mode: Annotated[
        str, typer.Option("--mode", "-m", help="Processed-output mode directory."),
    ] = "kinematic_p30_ttff_verify",
    stations: Annotated[
        list[str] | None,
        typer.Option("--station", "-s", help="4-char station ID; repeat to filter."),
    ] = None,
    reset_period: Annotated[
        int | None,
        typer.Option(
            "--reset-period",
            help="Reset period in seconds. Auto-detected from per-station .conf "
                 "if omitted; CLI flag overrides.",
        ),
    ] = None,
    interval: Annotated[
        int,
        typer.Option(
            "--interval", "-ti", help="Sampling interval in seconds (must match the run)."
        ),
    ] = _ttff.DEFAULT_SAMPLING_INTERVAL_SEC,
    output_root: Annotated[
        Path, typer.Option("--out", help="Processing-output root."),
    ] = Path("data/processed"),
    record_path: Annotated[
        Path | None,
        typer.Option(
            "--record",
            help="JSONL append path. Defaults to data/metadata/ttff.jsonl.",
        ),
    ] = None,
) -> None:
    """Extract TTFF per station from a processed DOY."""
    summaries = _ttff.analyze_doy(
        date_,
        mode=mode,
        output_root=output_root,
        stations=stations,
        reset_period_sec=reset_period,
        sampling_interval_sec=interval,
        record_path=record_path,
    )
    if not summaries:
        typer.echo("no TTFF summaries produced (check --mode and inputs)")
        return

    # Per-station lines (truncate if very many)
    for s in summaries[:20]:
        typer.echo(format_summary(s))
    if len(summaries) > 20:
        typer.echo(f"... ({len(summaries) - 20} more)")

    # Aggregate across stations (median of medians, mean fix rate, etc.)
    fix_rates = [s.fix_success_rate for s in summaries]
    p50s = [s.ttff_p50_sec for s in summaries if s.n_fixed > 0]
    p95s = [s.ttff_p95_sec for s in summaries if s.n_fixed > 0]

    typer.echo("")
    typer.echo(f"=== Aggregate across {len(summaries)} station(s) ===")
    typer.echo(f"  fix success rate: mean={100*sum(fix_rates)/len(fix_rates):.1f}% "
               f"min={100*min(fix_rates):.1f}% max={100*max(fix_rates):.1f}%")
    if p50s:
        typer.echo(f"  TTFF p50 across stations: median={sorted(p50s)[len(p50s)//2]:.0f}s "
                   f"min={min(p50s):.0f}s max={max(p50s):.0f}s")
        typer.echo(f"  TTFF p95 across stations: median={sorted(p95s)[len(p95s)//2]:.0f}s "
                   f"min={min(p95s):.0f}s max={max(p95s):.0f}s")


# ---------------------------------------------------------------------------
# reference-coords
# ---------------------------------------------------------------------------

@app.command("reference-coords")
def cmd_reference_coords(
    date_: Annotated[
        str | None,
        typer.Option("--date", "-d", help="Single target date (YYYY-MM-DD)."),
    ] = None,
    week: Annotated[
        str | None,
        typer.Option("--week", "-w", help="ISO week (YYYY-Www) — produces 7 target days."),
    ] = None,
    fixed_station_id: Annotated[
        str,
        typer.Option("--fixed-station", help="Anchor station ID (default Tsukuba1)."),
    ] = _reference_coords.DEFAULT_FIXED_STATION_ID,
    window_days: Annotated[
        int,
        typer.Option("--window-days", help="Half-window size in days (full window = 2N+1)."),
    ] = _reference_coords.DEFAULT_WINDOW_DAYS,
    f5_root: Annotated[
        Path,
        typer.Option("--f5-root", help="F5 archive root."),
    ] = _reference_coords.DEFAULT_F5_ROOT,
    output_root: Annotated[
        Path,
        typer.Option("--out", help="Reference-coords output root."),
    ] = _reference_coords.DEFAULT_OUTPUT_ROOT,
    jumps_path: Annotated[
        Path,
        typer.Option("--jumps", help="Curated GSI jumps TOML."),
    ] = _reference_coords.DEFAULT_JUMPS_PATH,
    allow_partial_window: Annotated[
        bool,
        typer.Option(
            "--allow-partial-window",
            help="Permit windows where F5 publication has not caught up.",
        ),
    ] = False,
) -> None:
    """Build reference coordinates by 15-day robust median (CMR)."""
    if (date_ is None) == (week is None):
        raise typer.BadParameter("provide exactly one of --date or --week")

    if date_ is not None:
        targets = [_parse_iso_date(date_)]
        out_path = _reference_coords.output_path_for_day(output_root, targets[0])
    else:
        assert week is not None
        year, iso_week = _parse_iso_week(week)
        targets = _iso_week_dates(year, iso_week)
        out_path = _reference_coords.output_path_for_week(output_root, year, iso_week)

    jumps = _reference_coords.load_jumps(jumps_path)

    combined, results = _reference_coords.compute_for_targets(
        targets,
        f5_root=f5_root,
        fixed_station_id=fixed_station_id,
        window_days=window_days,
        jumps=jumps,
        allow_partial_window=allow_partial_window,
    )
    _reference_coords.write_parquet(combined, out_path)
    _reference_coords.record_provenance(
        results,
        output_path=out_path,
        fixed_station_id=fixed_station_id,
        window_days=window_days,
    )

    typer.echo(f"wrote {out_path} ({len(combined)} rows, {len(results)} target dates)")
    for r in results:
        typer.echo(
            f"  {r.df['target_date'].iloc[0]}  "
            f"stations={len(r.df)}  "
            f"fixed_days_used={r.n_fixed_days_used}/{r.n_fixed_days_used + r.n_fixed_days_dropped}  "
            f"jumps_applied={len(r.applied_jump_dates)}"
        )


# ---------------------------------------------------------------------------
# epoch-errors (Stage 1)
# ---------------------------------------------------------------------------

@app.command("epoch-errors")
def cmd_epoch_errors(
    date_: Annotated[
        str, typer.Option("--date", "-d", help="Target date (YYYY-MM-DD).")
    ],
    mode: Annotated[
        str, typer.Option("--mode", "-m", help="Processing mode (= config name)."),
    ] = "kinematic_p30_verify",
    processed_root: Annotated[
        Path, typer.Option("--processed-root", help="Root containing {mode}/{year}/{doy}/*.pos."),
    ] = _epoch_errors.DEFAULT_PROCESSED_ROOT,
    ref_coords_path: Annotated[
        Path | None,
        typer.Option(
            "--ref-coords",
            help="Reference-coords Parquet. Auto-detect under "
                 "data/processed/reference_coords/{year}/ if omitted.",
        ),
    ] = None,
    output_root: Annotated[
        Path, typer.Option("--out", help="Epoch-errors output root."),
    ] = _epoch_errors.DEFAULT_OUTPUT_ROOT,
    stations: Annotated[
        list[str] | None,
        typer.Option("--station", "-s", help="Filter to one or more 4-char station IDs."),
    ] = None,
    engine_version: Annotated[
        str,
        typer.Option(
            "--engine-version",
            help="Override engine_version label written into the Parquet. "
                 "Auto-detect from binary by default if a process_doy run "
                 "produced the .pos files; this flag is for repackaging.",
        ),
    ] = "unknown",
) -> None:
    """Build per-epoch ENU error Parquet from CLASLIB .pos files (Stage 1)."""
    target = _parse_iso_date(date_)
    res = _epoch_errors.compute_epoch_errors(
        target,
        mode=mode,
        processed_root=processed_root,
        ref_coords_path=ref_coords_path,
        output_root=output_root,
        stations=stations,
        engine_version=engine_version,
    )
    typer.echo(
        f"wrote {res.parquet_path}  "
        f"stations={res.n_stations}  epochs={res.n_epochs}  "
        f"ref={res.ref_coords_source.name}"
    )


# ---------------------------------------------------------------------------
# accuracy (Stage 2a)
# ---------------------------------------------------------------------------

@app.command("accuracy")
def cmd_accuracy(
    date_: Annotated[
        str, typer.Option("--date", "-d", help="Target date (YYYY-MM-DD).")
    ],
    mode: Annotated[
        str, typer.Option("--mode", "-m", help="Processing mode."),
    ] = "kinematic_p30_verify",
    epoch_errors_root: Annotated[
        Path, typer.Option("--epoch-errors-root", help="Stage-1 root."),
    ] = _accuracy_stats.DEFAULT_EPOCH_ERRORS_ROOT,
    output_root: Annotated[
        Path, typer.Option("--out", help="Stage-2 output root."),
    ] = _accuracy_stats.DEFAULT_OUTPUT_ROOT,
) -> None:
    """Build daily accuracy stats (per-station + per-network cube) — Stage 2a."""
    target = _parse_iso_date(date_)
    res = _accuracy_stats.compute_daily(
        target,
        mode=mode,
        epoch_errors_root=epoch_errors_root,
        output_root=output_root,
    )
    typer.echo(
        f"wrote {res.station_parquet.name} + {res.network_parquet.name}  "
        f"stations={res.n_stations}  epochs={res.n_epochs}  "
        f"qualified={res.n_qualified_stations}"
    )
