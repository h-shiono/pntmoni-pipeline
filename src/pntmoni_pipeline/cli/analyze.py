"""``pntmoni-pipeline analyze ...`` subcommands."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer

from ..analysis import _ttff, format_summary

app = typer.Typer(no_args_is_help=True)

logger = logging.getLogger(__name__)


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
