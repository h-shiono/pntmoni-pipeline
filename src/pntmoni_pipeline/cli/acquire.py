"""``pntmoni-pipeline acquire ...`` subcommands."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from ..acquisition import (
    _base as _acq_base,
    _provenance as _acq_provenance,
    cddis_brdc,
    geonet_f5,
    geonet_rinex,
    igs_atx,
    igs_erp,
    qzss_l6,
)
from ..processing._aux_data import build_l5copy

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
    variant: Annotated[
        str,
        typer.Option(
            "--variant",
            help="GSI archive variant: 'f5' (ITRF2014, legacy) or 'f5_1' "
                 "(ITRF2020, current — primary CLAS reference for fy2026+).",
        ),
    ] = geonet_f5.DEFAULT_VARIANT,
    stations: Annotated[
        list[str] | None,
        typer.Option("--station", "-s", help="Filter by F5 station-ID prefix."),
    ] = None,
    overwrite: OverwriteOpt = False,
) -> None:
    """Acquire GEONET F5 / F5.1 coordinate snapshot for one year."""
    results = geonet_f5.fetch(
        year, dest, variant=variant, stations=stations, overwrite=overwrite,
    )
    typer.echo(f"acquired {len(results)} {variant} file(s) for {year}")


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


@app.command("igs-atx")
def cmd_igs_atx(
    dest: DestOpt = Path("data/raw"),
    overwrite: OverwriteOpt = True,
) -> None:
    """Acquire the official igs20.atx from files.igs.org."""
    r = igs_atx.fetch(dest, overwrite=overwrite)
    typer.echo(
        f"acquired {r.path.name} ({r.size_bytes} bytes, sha256={r.sha256[:12]})"
    )


@app.command("igs-erp")
def cmd_igs_erp(
    dest: DestOpt = Path("data/raw"),
    overwrite: OverwriteOpt = True,
) -> None:
    """Acquire and decompress IGS Ultra-Rapid ERP (igu00p01.erp.Z) from CDDIS."""
    compressed, plain = igs_erp.fetch(dest, overwrite=overwrite)
    typer.echo(
        f"acquired {compressed.path.name} ({compressed.size_bytes} bytes) "
        f"→ {plain.path.name} ({plain.size_bytes} bytes, sha256={plain.sha256[:12]})"
    )


@app.command("aux-data")
def cmd_aux_data(
    raw_root: DestOpt = Path("data/raw"),
    aux_dir: Annotated[
        Path,
        typer.Option(
            "--aux-dir",
            help="Production aux-data dir (will be populated with derived ATX, ERP, etc.).",
        ),
    ] = Path("configs/aux_data"),
    overwrite: OverwriteOpt = True,
) -> None:
    """One-shot: fetch igs20.atx + igu00p01.erp, derive L5copy ATX, stage into aux dir.

    The aux dir mirrors CLASLIB's data/ layout so production configs
    (kinematic_p30*.conf) can ``file-rcvantfile = data/igs20_L5copy.atx``
    and the engine ``--data-dir configs/aux_data`` resolves them.
    """
    atx_raw = igs_atx.fetch(raw_root, overwrite=overwrite)
    erp_compressed, erp_plain = igs_erp.fetch(raw_root, overwrite=overwrite)

    aux_dir.mkdir(parents=True, exist_ok=True)

    # Copy ERP into aux_dir at the filename expected by configs.
    aux_erp = aux_dir / "igu00p01.erp"
    aux_erp.write_bytes(erp_plain.path.read_bytes())

    # Derive L5copy ATX.
    aux_atx = aux_dir / "igs20_L5copy.atx"
    summary = build_l5copy(atx_raw.path, aux_atx, source_sha256=atx_raw.sha256)

    derived_sha = _acq_base.sha256_file(aux_atx)
    derived_record = _acq_base.AcquisitionResult(
        source="igs_atx_l5copy",
        url=f"derived-from:{atx_raw.url}",
        path=aux_atx,
        sha256=derived_sha,
        size_bytes=aux_atx.stat().st_size,
        retrieved_at=_acq_base.utcnow(),
        skipped=False,
        metadata={
            "source_sha256": atx_raw.sha256,
            "algorithm_version": "1",
            "g05_inserts": summary.n_g05_inserted,
            "j05_inserts": summary.n_j05_inserted,
            "antennas_seen": summary.n_antennas_seen,
        },
    )
    _acq_provenance.record(derived_record)

    typer.echo(
        f"aux-data staged at {aux_dir}:\n"
        f"  igs20.atx          sha256={atx_raw.sha256[:12]} ({atx_raw.size_bytes} bytes)\n"
        f"  igs20_L5copy.atx   sha256={derived_sha[:12]} "
        f"(G05+={summary.n_g05_inserted}, J05+={summary.n_j05_inserted}, "
        f"antennas={summary.n_antennas_seen})\n"
        f"  igu00p01.erp       sha256={erp_plain.sha256[:12]} ({erp_plain.size_bytes} bytes)"
    )
