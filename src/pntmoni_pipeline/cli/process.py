"""``pntmoni-pipeline process ...`` subcommands."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from ..processing import claslib_engine

app = typer.Typer(no_args_is_help=True)


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError as e:
        raise typer.BadParameter(f"date must be YYYY-MM-DD: {e}") from e


@app.command("claslib")
def cmd_claslib(
    date_: Annotated[
        str, typer.Option("--date", "-d", help="Target date (YYYY-MM-DD).")
    ],
    mode: Annotated[
        str, typer.Option("--mode", "-m", help="Config name in configs/ (without .conf).")
    ] = "kinematic_p30",
    stations: Annotated[
        list[str] | None,
        typer.Option(
            "--station", "-s",
            help="4-char station ID; repeat for multiple. Omit to process all stations.",
        ),
    ] = None,
    raw_root: Annotated[
        Path, typer.Option("--raw", help="Acquisition output root.")
    ] = Path("data/raw"),
    output_root: Annotated[
        Path, typer.Option("--out", help="Processing output root.")
    ] = Path("data/processed"),
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            help="rnx2rtkp scratch workspace. Defaults to data/work/{mode}/{year}/{doy}/.",
        ),
    ] = None,
    binary: Annotated[
        Path | None,
        typer.Option("--binary", help="Path to rnx2rtkp. Auto-detect under vendor/."),
    ] = None,
    data_dir: Annotated[
        Path,
        typer.Option("--data-dir", help="CLASLIB aux data directory (atx, blq, erp ...)."),
    ] = Path("vendor/claslib/data"),
    config_dir: Annotated[
        Path, typer.Option("--config-dir", help="Mode template config directory.")
    ] = Path("configs"),
    interval: Annotated[
        int, typer.Option("--interval", "-ti", help="Sampling interval (seconds).")
    ] = claslib_engine.DEFAULT_INTERVAL_SEC,
    workers: Annotated[
        int | None,
        typer.Option("--workers", "-j", help="Thread pool size. Defaults to cpu_count()."),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Re-run even if a .pos already exists.")
    ] = False,
) -> None:
    """Run CLASLIB rnx2rtkp on every station of one DOY."""
    target = _parse_date(date_)
    results = claslib_engine.process_doy(
        target,
        mode=mode,
        raw_root=raw_root,
        output_root=output_root,
        workspace=workspace,
        binary=binary,
        data_dir=data_dir,
        config_dir=config_dir,
        stations=stations,
        interval=interval,
        max_workers=workers,
        force=force,
    )
    ok = sum(1 for r in results if not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    typer.echo(
        f"processed {ok} station(s), skipped {skipped} for {target.isoformat()} (mode={mode})"
    )
