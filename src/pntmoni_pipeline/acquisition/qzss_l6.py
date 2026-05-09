"""QZSS L6 archive acquisition.

Mirrors ``get_l6.sh``: 24 hourly L6 files (suffixes A..X) per DOY from
``https://sys.qzss.go.jp/archives/l6/{year}/``, then concatenates into a
single ``{year}{doy}AX.l6`` consumed by CLASLIB / MRTKLIB.
"""
from __future__ import annotations

import logging
import string
from datetime import date
from pathlib import Path

from ._base import AcquisitionResult, sha256_file, utcnow
from ._http import download
from ._provenance import record as record_provenance

logger = logging.getLogger(__name__)

QSS_ROOT = "https://sys.qzss.go.jp/archives/l6"
SOURCE = "qzss_l6"
HOUR_SUFFIXES = list(string.ascii_uppercase[:24])  # A..X


def hourly_filename(year: int, doy: int, suffix: str) -> str:
    return f"{year}{doy:03d}{suffix}.l6"


def merged_filename(year: int, doy: int) -> str:
    return f"{year}{doy:03d}AX.l6"


def hourly_url(year: int, doy: int, suffix: str) -> str:
    return f"{QSS_ROOT}/{year}/{hourly_filename(year, doy, suffix)}"


def fetch(
    target: date,
    dest_root: Path,
    *,
    overwrite: bool = False,
) -> tuple[list[AcquisitionResult], AcquisitionResult]:
    """Download A..X hourly L6 files and produce a merged AX file.

    Returns
    -------
    (hourly_results, merged_result)
        ``hourly_results`` is the per-hour download records.
        ``merged_result`` is the provenance record for the concatenated file.
    """
    year = target.year
    doy = int(target.strftime("%j"))
    local_dir = dest_root / "l6" / f"{year}" / f"{doy:03d}"
    merged_path = local_dir / merged_filename(year, doy)

    if merged_path.exists() and not overwrite:
        logger.info("found %s — skipping", merged_path.name)
        sha = sha256_file(merged_path)
        merged = AcquisitionResult(
            source=f"{SOURCE}_merged",
            url=f"local://{merged_path}",
            path=merged_path,
            sha256=sha,
            size_bytes=merged_path.stat().st_size,
            retrieved_at=utcnow(),
            skipped=True,
            metadata={"date": target.isoformat(), "year": year, "doy": doy},
        )
        record_provenance(merged)
        return [], merged

    hourly: list[AcquisitionResult] = []
    for suffix in HOUR_SUFFIXES:
        fn = hourly_filename(year, doy, suffix)
        url = hourly_url(year, doy, suffix)
        dest = local_dir / fn
        hourly.append(
            download(
                url,
                dest,
                source=SOURCE,
                metadata={
                    "date": target.isoformat(),
                    "year": year,
                    "doy": doy,
                    "hour_suffix": suffix,
                },
                overwrite=overwrite,
            )
        )

    # Concatenate in A..X order (matches `cat ${year}${doy}?.l6`).
    merged_path.parent.mkdir(parents=True, exist_ok=True)
    with merged_path.open("wb") as out:
        for r in hourly:
            with r.path.open("rb") as f:
                while chunk := f.read(1024 * 1024):
                    out.write(chunk)

    sha = sha256_file(merged_path)
    merged = AcquisitionResult(
        source=f"{SOURCE}_merged",
        url=f"local://{merged_path}",
        path=merged_path,
        sha256=sha,
        size_bytes=merged_path.stat().st_size,
        retrieved_at=utcnow(),
        skipped=False,
        metadata={
            "date": target.isoformat(),
            "year": year,
            "doy": doy,
            "merged_from": [r.path.name for r in hourly],
        },
    )
    record_provenance(merged)
    logger.info("merged 24 L6 files into %s", merged_path.name)
    return hourly, merged
