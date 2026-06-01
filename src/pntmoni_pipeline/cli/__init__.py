"""Top-level Typer CLI for ``pntmoni-pipeline``."""
from __future__ import annotations

import logging

import typer

from .acquire import app as acquire_app
from .analyze import app as analyze_app
from .process import app as process_app
from .qc import app as qc_app
from .report import app as report_app

app = typer.Typer(
    name="pntmoni-pipeline",
    help="PNT Moni — local batch pipeline (data, processing, reports).",
    no_args_is_help=True,
)

app.add_typer(acquire_app, name="acquire", help="Data acquisition commands.")
app.add_typer(process_app, name="process", help="PPP-RTK processing commands.")
app.add_typer(qc_app, name="qc", help="Observation quality-control commands.")
app.add_typer(analyze_app, name="analyze", help="Post-processing analysis commands.")
app.add_typer(report_app, name="report", help="Monthly-report rendering.")


@app.callback()
def _root(
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Enable debug logging."),
) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )


if __name__ == "__main__":
    app()
