"""GEONET F5 coordinate solution acquisition (GSI).

Mirrors ``get_gsi_f5.sh``: yearly snapshot of GPS F5 coordinates under
``/data/coordinates_F5/GPS/{year}/``. F5 files are reference truth used
for coordinate-stability QC metrics.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from ._base import AcquisitionResult
from ._ftp import GSI_HOST, connect, download_file, filter_by_prefix, list_dir

logger = logging.getLogger(__name__)

ARCHIVE_ROOT = "/data/coordinates_F5/GPS"
SOURCE = "geonet_f5"


def remote_dir(year: int) -> str:
    return f"{ARCHIVE_ROOT}/{year}"


def fetch(
    year: int,
    dest_root: Path,
    *,
    stations: Iterable[str] | None = None,
    overwrite: bool = False,
) -> list[AcquisitionResult]:
    """Download F5 coordinate files for a year.

    Parameters
    ----------
    year : 4-digit GPS year of the F5 snapshot.
    dest_root : root for ``f5/{year}/`` layout.
    stations : optional 4-char station IDs to filter by; ``None`` mirrors all.
    """
    rdir = remote_dir(year)
    local_dir = dest_root / "f5" / f"{year}"

    results: list[AcquisitionResult] = []
    with connect() as ftp:
        entries = list_dir(ftp, rdir)
        if not entries:
            raise FileNotFoundError(f"no entries at ftp://{GSI_HOST}{rdir}")

        selected = filter_by_prefix(entries, stations)
        if not selected:
            logger.warning(
                "no matching F5 entries for stations=%s in %s",
                list(stations) if stations else None, rdir,
            )
            return results

        for entry in selected:
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
                        "year": year,
                        "station": name[:4],
                    },
                    overwrite=overwrite,
                )
            )
    return results
