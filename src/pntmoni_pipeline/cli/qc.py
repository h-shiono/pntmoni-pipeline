"""``pntmoni-pipeline qc ...`` subcommands."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from ..qc import _summary, _teqc

app = typer.Typer(no_args_is_help=True)


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError as e:
        raise typer.BadParameter(f"date must be YYYY-MM-DD: {e}") from e


@app.command("teqc")
def cmd_teqc(
    date_: Annotated[
        str, typer.Option("--date", "-d", help="Target date (YYYY-MM-DD).")
    ],
    raw_root: Annotated[
        Path, typer.Option("--raw", help="Acquisition RINEX root."),
    ] = _teqc.DEFAULT_RAW_RINEX_ROOT,
    output_root: Annotated[
        Path, typer.Option("--out", help="QC output root."),
    ] = _teqc.DEFAULT_OUTPUT_ROOT,
    stations: Annotated[
        list[str] | None,
        typer.Option(
            "--station", "-s",
            help="4-char station ID; repeat for multiple. Omit to process all.",
        ),
    ] = None,
    teqc: Annotated[
        Path, typer.Option("--teqc", help="teqc binary (Intel macOS, run via Rosetta 2)."),
    ] = _teqc.DEFAULT_TEQC,
    convbin: Annotated[
        Path, typer.Option("--convbin", help="RTKLIB convbin binary (native)."),
    ] = _teqc.DEFAULT_CONVBIN,
    workers: Annotated[
        int | None,
        typer.Option("--workers", "-j", help="Thread pool size. Defaults to cpu_count()."),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Re-run even if a .{yy}S exists."),
    ] = False,
) -> None:
    """Run teqc QC on GEONET RINEX OBS for one DOY (Stage 1 of QC)."""
    target = _parse_date(date_)
    res = _teqc.process_doy(
        target,
        raw_root=raw_root,
        output_root=output_root,
        teqc=teqc,
        convbin=convbin,
        stations=stations,
        max_workers=workers,
        force=force,
    )
    typer.echo(
        f"qc teqc {target.isoformat()}: "
        f"succeeded={res.n_succeeded}/{res.n_total}  "
        f"skipped={res.n_skipped}  failed={res.n_failed}  "
        f"wall={res.wall_sec:.1f}s  out={res.output_dir}"
    )
    if res.failed_stations:
        head = ", ".join(res.failed_stations[:10])
        more = f" (+{len(res.failed_stations) - 10} more)" if len(res.failed_stations) > 10 else ""
        typer.echo(f"  failed sample: {head}{more}")


@app.command("summarize")
def cmd_summarize(
    date_: Annotated[
        str, typer.Option("--date", "-d", help="Target date (YYYY-MM-DD).")
    ],
    input_root: Annotated[
        Path, typer.Option("--input-root", help="Root holding the .{yy}S summaries."),
    ] = _summary.DEFAULT_INPUT_ROOT,
    output_root: Annotated[
        Path, typer.Option("--out", help="Output root for the wide Parquet."),
    ] = _summary.DEFAULT_OUTPUT_ROOT,
) -> None:
    """Parse teqc .{yy}S summaries for one DOY → wide Parquet."""
    target = _parse_date(date_)
    res = _summary.summarize_doy(
        target, input_root=input_root, output_root=output_root,
    )
    typer.echo(
        f"qc summarize {target.isoformat()}: "
        f"stations={res.n_stations}  failed={res.n_failed}  "
        f"out={res.parquet_path}"
    )
