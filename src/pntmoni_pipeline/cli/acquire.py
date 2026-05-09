"""``pntmoni-pipeline acquire ...`` subcommands."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from ..acquisition import cddis_brdc, geonet_f5, geonet_rinex, qzss_l6

app = typer.Typer(no_args_is_help=True)

DateOpt = Annotated[
    str,
    typer.Option("--date", "-d", help="Target date (YYYY-MM-DD)."),
]
DestOpt = Annotated[
    Path,
    typer.Option("--dest", help="Destination root for downloaded files."),
]
OverwriteOpt = Annotated[
    bool,
    typer.Option("--overwrite", help="Re-download even if a local copy exists."),
]


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError as e:
        raise typer.BadParameter(f"date must be YYYY-MM-DD: {e}") from e


@app.command("rinex")
def cmd_rinex(
    date_: DateOpt,
    dest: DestOpt = Path("data/raw"),
    stations: Annotated[
        list[str] | None,
        typer.Option(
            "--station", "-s",
            help="4-char station ID to filter by; repeat for multiple. "
                 "Omit (default) to download all stations for the DOY.",
        ),
    ] = None,
    overwrite: OverwriteOpt = False,
) -> None:
    """Acquire GEONET RINEX OBS for one DOY (GSI FTP).

    By default, downloads all stations available in the DOY directory
    (~1300 entries for a recent date). Use ``--station`` to filter.
    """
    target = _parse_date(date_)
    results = geonet_rinex.fetch(
        target, dest, stations=stations, overwrite=overwrite,
    )
    typer.echo(f"acquired {len(results)} RINEX file(s) for {target.isoformat()}")


@app.command("f5")
def cmd_f5(
    year: Annotated[int, typer.Option("--year", "-y", help="GPS year (e.g. 2025).")],
    dest: DestOpt = Path("data/raw"),
    stations: Annotated[
        list[str] | None,
        typer.Option("--station", "-s", help="Filter by 4-char station ID."),
    ] = None,
    overwrite: OverwriteOpt = False,
) -> None:
    """Acquire GEONET F5 coordinate snapshot for one year."""
    results = geonet_f5.fetch(
        year, dest, stations=stations, overwrite=overwrite,
    )
    typer.echo(f"acquired {len(results)} F5 file(s) for {year}")


@app.command("brdc")
def cmd_brdc(
    date_: DateOpt,
    dest: DestOpt = Path("data/raw"),
    overwrite: OverwriteOpt = False,
) -> None:
    """Acquire CDDIS broadcast nav (BRDC) for one day."""
    target = _parse_date(date_)
    r = cddis_brdc.fetch(target, dest, overwrite=overwrite)
    typer.echo(f"acquired {r.path.name} ({r.size_bytes} bytes)")


@app.command("l6")
def cmd_l6(
    date_: DateOpt,
    dest: DestOpt = Path("data/raw"),
    overwrite: OverwriteOpt = False,
) -> None:
    """Acquire QZSS L6 hourly archive (A..X) and produce merged AX file."""
    target = _parse_date(date_)
    hourly, merged = qzss_l6.fetch(target, dest, overwrite=overwrite)
    typer.echo(
        f"acquired {len(hourly)} hourly L6 file(s); merged → {merged.path.name}"
    )
