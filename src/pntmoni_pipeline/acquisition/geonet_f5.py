"""GEONET F5 / F5.1 coordinate-solution acquisition (GSI).

Two GSI archives currently coexist:

- ``F5``  (``/data/coordinates_F5/GPS/{year}/``) — ITRF2014 frame.
  Legacy primary, snapshot publication delay ~1 month.
- ``F5.1`` (``/data/coordinates_F5.1/{year}/``) — ITRF2020 frame, no
  ``GPS/`` subdirectory. Becomes the CLAS reference for the April 2026
  fiscal half forward (per QSS announcement; verify the exact
  effective date in the operations notes). Snapshot stays current
  closer to the present than F5.

Local storage uses separate subdirs so the two archives never mix:

  data/raw/f5/{year}/{f5_id}.{yy}.pos
  data/raw/f5_1/{year}/{f5_id}.{yy}.pos

The ``--variant`` flag at the CLI selects which archive a run targets.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

from ._base import AcquisitionResult
from ._ftp import GSI_HOST, connect, download_file, filter_by_prefix, list_dir

logger = logging.getLogger(__name__)


class F5Variant(NamedTuple):
    label: str            # "f5" / "f5_1"
    remote_root: str      # FTP path
    local_subdir: str     # under dest_root/
    frame: str            # for documentation; not enforced


F5_VARIANTS: dict[str, F5Variant] = {
    "f5": F5Variant(
        label="f5",
        remote_root="/data/coordinates_F5/GPS",
        local_subdir="f5",
        frame="ITRF2014",
    ),
    "f5_1": F5Variant(
        label="f5_1",
        remote_root="/data/coordinates_F5.1",
        local_subdir="f5_1",
        frame="ITRF2020",
    ),
}

DEFAULT_VARIANT = "f5"      # backward-compat default; switch to "f5_1"
                            # when CLAS-side migration is confirmed
SOURCE_PREFIX = "geonet_"   # provenance source label = SOURCE_PREFIX + variant


def variant_for(label: str) -> F5Variant:
    if label not in F5_VARIANTS:
        raise ValueError(
            f"unknown F5 variant {label!r}; choose from {sorted(F5_VARIANTS)}"
        )
    return F5_VARIANTS[label]


def remote_dir(year: int, variant: str = DEFAULT_VARIANT) -> str:
    v = variant_for(variant)
    return f"{v.remote_root}/{year}"


def fetch(
    year: int,
    dest_root: Path,
    *,
    variant: str = DEFAULT_VARIANT,
    stations: Iterable[str] | None = None,
    overwrite: bool = False,
) -> list[AcquisitionResult]:
    """Download F5/F5.1 coordinate files for a year.

    Parameters
    ----------
    year : 4-digit GPS year of the snapshot.
    dest_root : root for ``{variant.local_subdir}/{year}/`` layout.
    variant : ``"f5"`` (legacy, ITRF2014) or ``"f5_1"`` (current, ITRF2020).
    stations : optional 6-char F5 station ID prefixes to filter by;
        ``None`` mirrors all.
    """
    v = variant_for(variant)
    rdir = f"{v.remote_root}/{year}"
    local_dir = dest_root / v.local_subdir / f"{year}"
    source = SOURCE_PREFIX + v.label

    results: list[AcquisitionResult] = []
    with connect() as ftp:
        entries = list_dir(ftp, rdir)
        if not entries:
            raise FileNotFoundError(f"no entries at ftp://{GSI_HOST}{rdir}")

        selected = filter_by_prefix(entries, stations)
        if not selected:
            logger.warning(
                "no matching %s entries for stations=%s in %s",
                v.label, list(stations) if stations else None, rdir,
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
                    source=source,
                    metadata={
                        "year": year,
                        "variant": v.label,
                        "frame": v.frame,
                        "station": name[:4],
                    },
                    overwrite=overwrite,
                )
            )
    return results


__all__ = [
    "DEFAULT_VARIANT",
    "F5Variant",
    "F5_VARIANTS",
    "fetch",
    "remote_dir",
    "variant_for",
]
