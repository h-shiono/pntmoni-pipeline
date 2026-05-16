"""``pntmoni-pipeline analyze ...`` subcommands."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated

import typer

from ..acquisition import geonet_f5
from ..analysis import (
    _accuracy_stats,
    _epoch_errors,
    _monthly,
    _reference_coords,
    _ttff,
    _ttff_stats,
    format_summary,
    qualification,
)

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
        Path | None,
        typer.Option(
            "--f5-root",
            help="F5 archive root. Defaults to data/raw/{f5-variant} when omitted.",
        ),
    ] = None,
    f5_variant: Annotated[
        str,
        typer.Option(
            "--f5-variant",
            help="GSI variant: 'auto' (date-based: F5 pre-2026-04-01, F5.1 "
                 "after; per QSS IS-QZSS_260327), 'f5' (ITRF2014, force), "
                 "or 'f5_1' (ITRF2020, force). Resolves f5_root to "
                 "data/raw/{variant} unless --f5-root is set.",
        ),
    ] = "auto",
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
            help="Permit windows where F5 publication has not caught up. "
                 "Fail-open: treats below-threshold as warn instead of error.",
        ),
    ] = False,
    min_fixed_days: Annotated[
        int,
        typer.Option(
            "--min-fixed-days",
            help="Minimum non-NaN fixed-station days for a production-grade "
                 "reference (out of 2*window_days+1). Default 14 admits one "
                 "jump-NaN'd day; partial windows fall below and require "
                 "--allow-partial-window.",
        ),
    ] = _reference_coords.DEFAULT_MIN_FIXED_DAYS,
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

    if f5_root is None:
        if f5_variant == "auto":
            chosen = {geonet_f5.variant_for_date(t) for t in targets}
            if len(chosen) > 1:
                raise typer.BadParameter(
                    f"targets span the F5→F5.1 switch "
                    f"({geonet_f5.CLAS_F51_EFFECTIVE_DATE.isoformat()}); "
                    f"split into two runs with explicit --f5-variant"
                )
            f5_variant = chosen.pop()
        if f5_variant not in ("f5", "f5_1"):
            raise typer.BadParameter(f"unknown --f5-variant: {f5_variant}")
        f5_root = Path("data/raw") / f5_variant

    jumps = _reference_coords.load_jumps(jumps_path)

    combined, results = _reference_coords.compute_for_targets(
        targets,
        f5_root=f5_root,
        fixed_station_id=fixed_station_id,
        window_days=window_days,
        jumps=jumps,
        allow_partial_window=allow_partial_window,
        min_fixed_days=min_fixed_days,
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


# ---------------------------------------------------------------------------
# ttff-stats (Stage 2b — strict criterion: Q==4 AND error≤threshold)
# ---------------------------------------------------------------------------

@app.command("ttff-stats")
def cmd_ttff_stats(
    date_: Annotated[
        str, typer.Option("--date", "-d", help="Target date (YYYY-MM-DD).")
    ],
    mode: Annotated[
        str, typer.Option("--mode", "-m", help="Processing mode."),
    ] = "kinematic_p30_ttff_verify",
    epoch_errors_root: Annotated[
        Path, typer.Option("--epoch-errors-root", help="Stage-1 root."),
    ] = _accuracy_stats.DEFAULT_EPOCH_ERRORS_ROOT,
    output_root: Annotated[
        Path, typer.Option("--out", help="Stage-2 output root."),
    ] = _accuracy_stats.DEFAULT_OUTPUT_ROOT,
    reset_period: Annotated[
        int,
        typer.Option(
            "--reset-period",
            help="Reset period in seconds (must match misc-regularly).",
        ),
    ] = _ttff_stats.DEFAULT_RESET_PERIOD_SEC,
    horizontal_threshold: Annotated[
        float | None,
        typer.Option(
            "--h-threshold",
            help="Horizontal accuracy threshold (m). Auto from mode if omitted.",
        ),
    ] = None,
    vertical_threshold: Annotated[
        float | None,
        typer.Option(
            "--v-threshold",
            help="Vertical accuracy threshold (m). Auto from mode if omitted.",
        ),
    ] = None,
) -> None:
    """Build daily strict-TTFF stats — Stage 2b."""
    target = _parse_iso_date(date_)
    res = _ttff_stats.compute_daily(
        target,
        mode=mode,
        epoch_errors_root=epoch_errors_root,
        output_root=output_root,
        reset_period_sec=reset_period,
        horizontal_threshold_m=horizontal_threshold,
        vertical_threshold_m=vertical_threshold,
    )
    typer.echo(
        f"wrote {res.station_parquet.name} + {res.network_parquet.name}  "
        f"H={res.horizontal_threshold_m:.3f}  V={res.vertical_threshold_m:.3f}  "
        f"reset={res.reset_period_sec}s  qualified={res.n_qualified_stations}"
    )


# ---------------------------------------------------------------------------
# monthly rollup (Stage 2 monthly — accuracy + ttff in one shot)
# ---------------------------------------------------------------------------

@app.command("monthly")
def cmd_monthly(
    month: Annotated[
        str, typer.Option("--month", "-m", help="Target month (YYYY-MM).")
    ],
    mode: Annotated[
        str, typer.Option("--mode", help="Processing mode."),
    ] = "kinematic_p30_ttff_verify",
    epoch_errors_root: Annotated[
        Path, typer.Option("--epoch-errors-root", help="Stage-1 root."),
    ] = _accuracy_stats.DEFAULT_EPOCH_ERRORS_ROOT,
    output_root: Annotated[
        Path, typer.Option("--out", help="Stage-2 output root."),
    ] = _accuracy_stats.DEFAULT_OUTPUT_ROOT,
    reset_period: Annotated[
        int, typer.Option("--reset-period", help="Reset period in seconds."),
    ] = _ttff_stats.DEFAULT_RESET_PERIOD_SEC,
) -> None:
    """Pool a month of daily epoch_errors and emit monthly Parquets."""
    try:
        year_str, month_str = month.split("-")
        year, month_int = int(year_str), int(month_str)
    except (ValueError, AttributeError) as e:
        raise typer.BadParameter(f"month must be YYYY-MM: {e}") from e
    res = _monthly.compute_monthly(
        year, month_int,
        mode=mode,
        epoch_errors_root=epoch_errors_root,
        output_root=output_root,
        reset_period_sec=reset_period,
    )
    typer.echo(
        f"wrote 4 Parquets for {res.period} (mode={res.mode})  "
        f"pooled {res.n_dates_pooled} day(s)"
    )



@app.command("qualification")
def cmd_qualification(
    ref_date_s: Annotated[
        str, typer.Option("--ref-date", help="Window end date (inclusive), YYYY-MM-DD."),
    ],
    window_days: Annotated[
        int, typer.Option("--window-days", help="Length of the rolling QC window in days."),
    ] = 90,
    ng_days_max: Annotated[
        int | None,
        typer.Option(
            "--ng-days",
            help="Maximum NG-days a station may have and still qc_pass. "
                 "Default: ceil(n_days_loaded * 0.038) per legacy ratio.",
        ),
    ] = None,
    qc_summary_root: Annotated[
        Path, typer.Option("--qc-root", help="Root of qc_summary parquets."),
    ] = Path("data/processed/qc_summary"),
    eval_periods_path: Annotated[
        Path,
        typer.Option(
            "--eval-periods",
            help="CLAS official evaluation periods TOML (force-include set).",
        ),
    ] = Path("configs/stations/eval_periods.toml"),
    out_of_service_path: Annotated[
        Path,
        typer.Option(
            "--out-of-service",
            help="Hard-veto stations TOML (CLAS-out-of-coverage / decommissioned).",
        ),
    ] = Path("configs/stations/out_of_service.toml"),
    network_assignments_path: Annotated[
        Path,
        typer.Option(
            "--network-assignments",
            help="GEONET station → netid lookup TOML (for output column).",
        ),
    ] = Path("configs/stations/network_assignments.toml"),
    out_root: Annotated[
        Path,
        typer.Option(
            "--out",
            help="Output directory for {ref_date}_{window}d.parquet.",
        ),
    ] = Path("data/processed/station_qualification"),
    provenance_log: Annotated[
        Path,
        typer.Option(
            "--provenance-log",
            help="JSONL provenance log (appended).",
        ),
    ] = Path("data/metadata/qualification.jsonl"),
) -> None:
    """Run the absolute-evaluation station qualification."""
    ref_date = _parse_iso_date(ref_date_s)
    result = qualification.qualify(
        ref_date,
        window_days=window_days,
        ng_days_max=ng_days_max,
        qc_summary_root=qc_summary_root,
        eval_periods_path=eval_periods_path,
        out_of_service_path=out_of_service_path,
        network_assignments_path=network_assignments_path,
    )
    dest = out_root / f"{ref_date.isoformat()}_{window_days}d.parquet"
    qualification.write_parquet(result, dest)
    qualification.write_provenance_jsonl(result, provenance_log)
    n_q = sum(1 for r in result.rows if r["qualified"])
    n_qc = sum(1 for r in result.rows if r["qc_pass"])
    n_fe = sum(1 for r in result.rows if r["force_eval"])
    n_oos = sum(1 for r in result.rows if r["out_of_service"])
    typer.echo(
        f"qualification for ref_date={ref_date.isoformat()} window={window_days}d "
        f"ng_days_max={result.ng_days_max}\n"
        f"  qualified : {n_q}/{len(result.rows)}\n"
        f"  qc_pass   : {n_qc}\n"
        f"  force_eval: {n_fe}\n"
        f"  out_of_svc: {n_oos}\n"
        f"  wrote     : {dest}"
    )
