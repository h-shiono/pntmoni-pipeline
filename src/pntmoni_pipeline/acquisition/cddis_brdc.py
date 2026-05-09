"""CDDIS broadcast navigation acquisition.

Mirrors ``get_brdc.sh``: pulls the daily merged BRDC RNX from
``https://cddis.nasa.gov/archive/gnss/data/daily/``. Earthdata Login
credentials are required (env or ``.netrc``).
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from ._base import AcquisitionResult
from ._http import download, earthdata_auth

logger = logging.getLogger(__name__)

CDDIS_ROOT = "https://cddis.nasa.gov/archive/gnss/data/daily"
SOURCE = "cddis_brdc"


def filename(year: int, doy: int) -> str:
    return f"BRDC00IGS_R_{year}{doy:03d}0000_01D_MN.rnx.gz"


def url(year: int, doy: int) -> str:
    yy = f"{year % 100:02d}"
    return f"{CDDIS_ROOT}/{year}/{doy:03d}/{yy}p/{filename(year, doy)}"


def fetch(
    target: date,
    dest_root: Path,
    *,
    overwrite: bool = False,
) -> AcquisitionResult:
    """Download the merged BRDC navigation file for one day.

    Stores under ``brdc/{year}/{filename}``.
    """
    year = target.year
    doy = int(target.strftime("%j"))
    fn = filename(year, doy)
    full_url = url(year, doy)
    dest = dest_root / "brdc" / f"{year}" / fn

    auth = earthdata_auth()
    if auth is None:
        raise RuntimeError(
            "Earthdata credentials required for CDDIS — set "
            "EARTHDATA_USER/EARTHDATA_PASSWORD or configure ~/.netrc"
        )

    return download(
        full_url,
        dest,
        source=SOURCE,
        auth=auth,
        metadata={
            "date": target.isoformat(),
            "year": year,
            "doy": doy,
        },
        overwrite=overwrite,
    )
