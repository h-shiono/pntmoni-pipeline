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
            help="Comma-separated render formats: html, pdf (alias:"
                 " typst). Default html. PDF renders via Quarto's bundled"
                 " Typst (ADR 0017 Phase D) with the provenance cover from"
                 " reports/templates/typst-template.typ; system fonts only.",
        ),
    ] = "html",
    langs: Annotated[
        str,
        typer.Option(
            "--langs",
            help="Comma-separated languages to render: ja, en. Default both."
                 " Each renders via `--profile <lang>` into its own"
                 " <out>/<lang>/ subdir (single-source bilingual template).",
        ),
    ] = "ja,en",
    revisions: Annotated[
        list[str] | None,
        typer.Option(
            "--revision",
            help="Post-publication correction row (repeatable), format"
                 " 'VERSION|DATE|NOTE_JA|NOTE_EN', e.g."
                 " '1.1|2026-07-08|文言修正|Wording fix'. Requires"
                 " --initial-pub-date so the v1.0 row keeps its original"
                 " date on the re-render.",
        ),
    ] = None,
    initial_pub_date: Annotated[
        str,
        typer.Option(
            "--initial-pub-date",
            help="Original v1.0 publication date (YYYY-MM-DD) for"
                 " correction re-renders; default stamps today.",
        ),
    ] = "",
) -> None:
    """Drive the monthly report: gather → config_hash → params → (render)."""
    _formats = tuple(
        f.strip().lower() for f in formats.split(",") if f.strip()
    )
    bad = [f for f in _formats if f not in ("html", "pdf", "typst")]
    if bad:
        raise typer.BadParameter(
            f"unknown format(s): {bad} (allowed: html, pdf, typst)"
        )
    _langs = tuple(
        l.strip().lower() for l in langs.split(",") if l.strip()
    )
    bad_l = [l for l in _langs if l not in ("ja", "en")]
    if bad_l:
        raise typer.BadParameter(f"unknown lang(s): {bad_l} (allowed: ja, en)")
    _revisions: list[dict[str, str]] = []
    for spec in revisions or []:
        parts = [p.strip() for p in spec.split("|")]
        if len(parts) != 4 or not all(parts[:2]):
            raise typer.BadParameter(
                f"bad --revision {spec!r}"
                " (expected 'VERSION|DATE|NOTE_JA|NOTE_EN')"
            )
        _revisions.append({
            "version": parts[0], "date": parts[1],
            "note_ja": parts[2], "note_en": parts[3],
        })
    if _revisions and not initial_pub_date:
        raise typer.BadParameter(
            "--revision requires --initial-pub-date (the v1.0 row must"
            " keep its original publication date on a re-render)"
        )
    result = reports.run_monthly(
        period=period, mode=mode, stream=stream,
        engine_version=engine_version, data_mode=data_mode,
        template=template, output_root=output_root,
        processing_log=processing_log, do_render=render,
        formats=_formats, langs=_langs,
        revisions=_revisions, initial_pub_date=initial_pub_date,
    )
    typer.echo(
        f"report monthly {result.period} stream={result.stream} mode={result.mode}\n"
        f"  config_hash : {result.config_hash_display}  (full -> {processing_log})\n"
        f"  inputs      : {result.inputs_status}\n"
        f"  params      : {result.params_path}\n"
        f"  rendered    : {result.rendered}"
        + (f"\n  outputs     : {result.outputs}" if result.outputs else "")
    )
