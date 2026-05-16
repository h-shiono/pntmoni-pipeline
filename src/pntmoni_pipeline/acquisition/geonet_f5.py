"""GEONET F5 / F5.1 / R5 / R5.1 coordinate-solution acquisition (GSI).

GSI publishes the GEONET station-coordinate time series in two
"flavours" — *final* and *rapid* — each in two reference-frame variants:

- ``F5``   Final, ITRF2014  (``/data/coordinates_F5/GPS/``).
- ``F5.1`` Final, ITRF2020  (``/data/coordinates_F5.1/``).
- ``R5``   Rapid, ITRF2014  (``/data/coordinates_R5/GPS/``).
- ``R5.1`` Rapid, ITRF2020  (``/data/coordinates_R5.1/``).

The final products are the peer-reviewed reference (Shiono & Kubo 2026,
NAVIGATION) but lag ~1 month behind observation. The rapid products
publish within ~1 week of observation (target ~2 days). PNT Moni uses
the rapid solutions for its monthly **速報** (preliminary) reports and
the final solutions for the **続報** (follow-up) reports — see
``pntmoni-docs/70-decisions/adr-0013.md``.

CLAS switches from the ITRF2014 lineage (F5/R5) to ITRF2020 (F5.1/R5.1)
on :data:`CLAS_F51_EFFECTIVE_DATE` per QSS announcement IS-QZSS_260327.

Local storage uses separate subdirs so the four archives never mix::

    data/raw/f5/{year}/{f5_id}.{yy}.pos
    data/raw/f5_1/{year}/{f5_id}.{yy}.pos
    data/raw/r5/{year}/{f5_id}.{yy}.pos
    data/raw/r5_1/{year}/{f5_id}.{yy}.pos

The ``--variant`` flag at the CLI selects which archive a run targets.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import NamedTuple

from ._base import AcquisitionResult
from ._ftp import GSI_HOST, connect, download_file, filter_by_prefix, list_dir

logger = logging.getLogger(__name__)


class F5Variant(NamedTuple):
    label: str            # "f5" / "f5_1" / "r5" / "r5_1"
    remote_root: str      # FTP path
    local_subdir: str     # under dest_root/
    frame: str            # for documentation; not enforced
    is_rapid: bool        # True for R5 / R5.1, False for F5 / F5.1


F5_VARIANTS: dict[str, F5Variant] = {
    "f5": F5Variant(
        label="f5",
        remote_root="/data/coordinates_F5/GPS",
        local_subdir="f5",
        frame="ITRF2014",
        is_rapid=False,
    ),
    "f5_1": F5Variant(
        label="f5_1",
        remote_root="/data/coordinates_F5.1",
        local_subdir="f5_1",
        frame="ITRF2020",
        is_rapid=False,
    ),
    "r5": F5Variant(
        label="r5",
        remote_root="/data/coordinates_R5/GPS",
        local_subdir="r5",
        frame="ITRF2014",
        is_rapid=True,
    ),
    "r5_1": F5Variant(
        label="r5_1",
        remote_root="/data/coordinates_R5.1",
        local_subdir="r5_1",
        frame="ITRF2020",
        is_rapid=True,
    ),
}

DEFAULT_VARIANT = "f5"      # backward-compat default for explicit
                            # ``acquire`` runs; ``--variant`` is recommended
SOURCE_PREFIX = "geonet_"   # provenance source label = SOURCE_PREFIX + variant

# CLAS evaluation officially switches from the ITRF2014 lineage (F5/R5)
# to ITRF2020 (F5.1/R5.1) on this date per QSS announcement
# IS-QZSS_260327 (https://qzss.go.jp/info/information/is-qzss_260327.html).
# Pre-switch dates are evaluated against F5/R5; post-switch against F5.1/R5.1.
CLAS_F51_EFFECTIVE_DATE = date(2026, 4, 1)


def variant_for_date(target: date, *, rapid: bool = False) -> str:
    """Return the GSI variant CLAS officially uses for ``target``.

    Pre-:data:`CLAS_F51_EFFECTIVE_DATE` → ``"f5"`` / ``"r5"`` (ITRF2014).
    On or after that date → ``"f5_1"`` / ``"r5_1"`` (ITRF2020).
    """
    post_switch = target >= CLAS_F51_EFFECTIVE_DATE
    if rapid:
        return "r5_1" if post_switch else "r5"
    return "f5_1" if post_switch else "f5"


def rapid_variant_for_date(target: date) -> str:
    """Convenience alias for ``variant_for_date(target, rapid=True)``."""
    return variant_for_date(target, rapid=True)


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
    """Download F5/F5.1/R5/R5.1 coordinate files for a year.

    Parameters
    ----------
    year : 4-digit GPS year of the snapshot.
    dest_root : root for ``{variant.local_subdir}/{year}/`` layout.
    variant : one of ``"f5"`` (legacy final), ``"f5_1"`` (current final),
        ``"r5"`` (legacy rapid), ``"r5_1"`` (current rapid). See
        :data:`F5_VARIANTS`.
    stations : optional F5 station-ID prefixes to filter by;
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
                        "is_rapid": v.is_rapid,
                        "station": name[:4],
                    },
                    overwrite=overwrite,
                )
            )
    return results


__all__ = [
    "CLAS_F51_EFFECTIVE_DATE",
    "DEFAULT_VARIANT",
    "F5Variant",
    "F5_VARIANTS",
    "fetch",
    "rapid_variant_for_date",
    "remote_dir",
    "variant_for",
    "variant_for_date",
]
