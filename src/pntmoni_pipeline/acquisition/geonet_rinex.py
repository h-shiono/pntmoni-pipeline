"""GEONET RINEX OBS acquisition (GSI ``GRJE_3.02`` archive).

Mirrors the behaviour of ``get_gsi_rinex.sh`` (1300+ stations per day in
the GRJE_3.02 v3.02 multi-GNSS archive) but adds optional station
filtering so we don't have to mirror the entire DOY directory.

Attribution required by GEONET PDL 1.0 — handled at report-render time.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from ._base import AcquisitionResult
from ._ftp import GSI_HOST, connect, download_file, filter_by_prefix, list_dir

logger = logging.getLogger(__name__)

ARCHIVE_ROOT = "/data/GRJE_3.02"
SOURCE = "geonet_rinex"


def remote_dir(year: int, doy: int) -> str:
    return f"{ARCHIVE_ROOT}/{year}/{doy:03d}"


def fetch(
    target: date,
    dest_root: Path,
    *,
    stations: Iterable[str] | None = None,
    overwrite: bool = False,
) -> list[AcquisitionResult]:
    """Download GEONET RINEX OBS for one DOY.

    Parameters
    ----------
    target : the calendar date to acquire.
    dest_root : root for ``rinex/{year}/{doy:03d}/`` layout.
    stations : optional 4-char station IDs (e.g. ["0231"]); ``None`` mirrors all.
    """
    year = target.year
    doy = int(target.strftime("%j"))
    rdir = remote_dir(year, doy)
    local_dir = dest_root / "rinex" / f"{year}" / f"{doy:03d}"

    results: list[AcquisitionResult] = []
    with connect() as ftp:
        entries = list_dir(ftp, rdir)
        if not entries:
            raise FileNotFoundError(f"no entries at ftp://{GSI_HOST}{rdir}")

        # nlst() may return either bare filenames or full paths depending
        # on server; normalize to basenames for filtering, keep full path for RETR.
        selected_full = filter_by_prefix(entries, stations)
        if not selected_full:
            logger.warning(
                "no matching entries for stations=%s in %s",
                list(stations) if stations else None, rdir,
            )
            return results

        for entry in selected_full:
            name = Path(entry).name
            remote_path = entry if entry.startswith("/") else f"{rdir}/{name}"
            local_path = local_dir / name
            results.append(
                download_file(
                    ftp,
                    remote_path,
                    local_path,
                    source=SOURCE,
                    metadata={
                        "date": target.isoformat(),
                        "year": year,
                        "doy": doy,
                        "station": name[:4],
                    },
                    overwrite=overwrite,
                )
            )
    return results
