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
from ..acquisition.satellite_outages import (
    _provenance as _so_provenance,
    _writers as _so_writers,
    events as _so_events,
    nagu as _so_nagu,
    nanu as _so_nanu,
    naqu as _so_naqu,
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
            help="GSI Final archive variant: 'f5' (ITRF2014, legacy) or "
                 "'f5_1' (ITRF2020, current — primary CLAS reference for fy2026+).",
        ),
    ] = "f5",
    stations: Annotated[
        list[str] | None,
        typer.Option("--station", "-s", help="Filter by F5 station-ID prefix."),
    ] = None,
    overwrite: OverwriteOpt = False,
) -> None:
    """Acquire GEONET F5 / F5.1 (Final) coordinate snapshot for one year."""
    if variant not in {"f5", "f5_1"}:
        raise typer.BadParameter(
            f"acquire f5 expects 'f5' or 'f5_1'; got {variant!r}. "
            f"Use 'acquire r5' for rapid solutions."
        )
    results = geonet_f5.fetch(
        year, dest, variant=variant, stations=stations, overwrite=overwrite,
    )
    typer.echo(f"acquired {len(results)} {variant} file(s) for {year}")


@app.command("r5")
def cmd_r5(
    year: Annotated[int, typer.Option("--year", "-y", help="GPS year (e.g. 2026).")],
    dest: DestOpt = Path("data/raw"),
    variant: Annotated[
        str,
        typer.Option(
            "--variant",
            help="GSI Rapid archive variant: 'r5' (ITRF2014, legacy) or "
                 "'r5_1' (ITRF2020, current — basis for the Monthly 速報 "
                 "report; F5.1 続報 supersedes when published).",
        ),
    ] = "r5_1",
    stations: Annotated[
        list[str] | None,
        typer.Option("--station", "-s", help="Filter by F5 station-ID prefix."),
    ] = None,
    overwrite: OverwriteOpt = False,
) -> None:
    """Acquire GEONET R5 / R5.1 (Rapid) coordinate snapshot for one year.

    Rapid solutions publish within ~1 week of observation (target ~2 days),
    versus ~1-month latency for the Final F5 / F5.1 lineage. Use this for
    the Monthly 速報 ENU computation; rerun against F5/F5.1 when the Final
    snapshot lands. See ADR 0013.
    """
    if variant not in {"r5", "r5_1"}:
        raise typer.BadParameter(
            f"acquire r5 expects 'r5' or 'r5_1'; got {variant!r}. "
            f"Use 'acquire f5' for final solutions."
        )
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


@app.command("satellite-outages")
def cmd_satellite_outages(
    constellation: Annotated[
        str,
        typer.Option(
            "--constellation", "-c",
            help="Filter to one constellation: gps | gal | qzs | all (default).",
        ),
    ] = "all",
    year: Annotated[
        int | None,
        typer.Option(
            "--year", "-y",
            help="Target year for NANU/NAQU enumeration. Defaults to current year.",
        ),
    ] = None,
    raw_dest: Annotated[
        Path,
        typer.Option(
            "--raw-dest",
            help="Root directory for raw_notices Parquet output.",
        ),
    ] = Path("data/processed/satellite_outages/raw_notices"),
    events_dest: Annotated[
        Path,
        typer.Option(
            "--events-dest",
            help="Destination path for normalised events Parquet.",
        ),
    ] = Path("data/processed/satellite_outages/events.parquet"),
) -> None:
    """Acquire NANU / NAGU / NAQU satellite outage notices.

    Per ADR 0012 (pntmoni-docs), this pipeline is the single producer
    of normalised satellite-outage data. Raw notices are archived
    per-(constellation, month); events are normalised into a single
    Parquet keyed by SVN.
    """
    import datetime as _dt
    target_year = year or _dt.date.today().year
    selectors = {"gps", "gal", "qzs"} if constellation == "all" else {constellation}
    if not selectors <= {"gps", "gal", "qzs"}:
        raise typer.BadParameter(f"unknown constellation: {constellation}")

    all_raw: list = []

    if "gps" in selectors:
        typer.echo(f"acquiring NANU for {target_year} ...")
        results = _so_nanu.fetch_year(target_year)
        all_raw.extend(r for r, _ in results)
        typer.echo(f"  {len(results)} NANU records")

    if "qzs" in selectors:
        typer.echo(f"acquiring NAQU for {target_year} ...")
        results = _so_naqu.fetch_year(target_year)
        all_raw.extend(r for r, _ in results)
        typer.echo(f"  {len(results)} NAQU records")

    if "gal" in selectors:
        typer.echo("acquiring NAGU (RSS, recent) ...")
        results = _so_nagu.fetch_recent()
        all_raw.extend(results)
        typer.echo(f"  {len(results)} NAGU records")

    if not all_raw:
        typer.echo("no notices fetched; aborting before writing Parquets.")
        return

    written = _so_writers.write_raw_notices(all_raw, dest_root=raw_dest)
    events_list = _so_events.normalize(all_raw)
    events_path = _so_writers.write_events(events_list, dest=events_dest)

    for path, n in written.items():
        _so_provenance.record(
            constellation=path.parent.parent.name,
            source_url=str(path),
            n_notices=n,
            raw_parquet=path,
            events_parquet=events_path,
            extras={"year": target_year},
        )

    typer.echo(
        f"\n--- summary ---\n"
        f"  raw notices : {sum(written.values())} rows across "
        f"{len(written)} parquet(s)\n"
        f"  events      : {len(events_list)} normalised → {events_path}"
    )
