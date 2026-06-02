"""``pntmoni-pipeline report ...`` subcommands."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer

from .. import reports

app = typer.Typer(no_args_is_help=True)
logger = logging.getLogger(__name__)


@app.command("monthly")
def cmd_monthly(
    period: Annotated[
        str, typer.Option("--period", help="Reporting period, YYYY-MM."),
    ],
    mode: Annotated[
        str, typer.Option("--mode", help="Processing mode (matches the .conf basename)."),
    ] = "kinematic_p30_verify",
    stream: Annotated[
        str, typer.Option("--stream", help="Evaluation stream: rapid | final."),
    ] = "final",
    engine_version: Annotated[
        str, typer.Option("--engine-version", help="pntmoni-claslib version tag."),
    ] = reports.driver.DEFAULT_ENGINE_VERSION,
    data_mode: Annotated[
        str, typer.Option("--data-mode", help="Report data_mode tag: live | trial | synthetic."),
    ] = "live",
    template: Annotated[
        Path, typer.Option("--template", help="Path to the Quarto template (.qmd)."),
    ] = reports.DEFAULT_TEMPLATE,
    output_root: Annotated[
        Path, typer.Option("--out", help="Output root: {out}/{stream}/{period}/..."),
    ] = reports.DEFAULT_OUTPUT_ROOT,
    processing_log: Annotated[
        Path, typer.Option("--processing-log", help="JSONL provenance (appended)."),
    ] = reports.DEFAULT_PROCESSING_LOG,
    render: Annotated[
        bool,
        typer.Option(
            "--render/--no-render",
            help="Invoke `quarto render` (requires Quarto on PATH; the qmd"
                 " must consume params for its output to reflect them).",
        ),
    ] = False,
    formats: Annotated[
        str,
        typer.Option(
            "--formats",
            help="Comma-separated render formats: html, pdf. Default html."
                 " PDF needs matplotlib's PDF backend to handle the figures'"
                 " CJK fonts (Hiragino etc. fail the ASCII-only Name encoder"
                 " on matplotlib<3.x); enable only if a working stack is"
                 " staged.",
        ),
    ] = "html",
) -> None:
    """Drive the monthly report: gather → config_hash → params → (render)."""
    _formats = tuple(
        f.strip().lower() for f in formats.split(",") if f.strip()
    )
    bad = [f for f in _formats if f not in ("html", "pdf")]
    if bad:
        raise typer.BadParameter(f"unknown format(s): {bad} (allowed: html, pdf)")
    result = reports.run_monthly(
        period=period, mode=mode, stream=stream,
        engine_version=engine_version, data_mode=data_mode,
        template=template, output_root=output_root,
        processing_log=processing_log, do_render=render,
        formats=_formats,
    )
    typer.echo(
        f"report monthly {result.period} stream={result.stream} mode={result.mode}\n"
        f"  config_hash : {result.config_hash_display}  (full -> {processing_log})\n"
        f"  inputs      : {result.inputs_status}\n"
        f"  params      : {result.params_path}\n"
        f"  rendered    : {result.rendered}"
        + (f"\n  outputs     : {result.outputs}" if result.outputs else "")
    )
