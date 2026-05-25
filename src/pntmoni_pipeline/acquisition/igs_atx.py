"""IGS antenna PCV (igs20.atx) acquisition.

Fetches the official ``igs20.atx`` from ``files.igs.org``. The file is
the IGS20 antenna phase-centre variation table used by CLASLIB
``rnx2rtkp`` via the ``file-rcvantfile`` config entry. It is mutable
upstream (IGS publishes updates as antenna calibrations are refined),
so each fetch is recorded in ``data/metadata/acquisition.jsonl`` with
SHA-256 + retrieved_at for reproducibility.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from ._base import AcquisitionResult
from ._http import download

logger = logging.getLogger(__name__)

DEFAULT_URL = "https://files.igs.org/pub/station/general/igs20.atx"
SOURCE = "igs_atx"
DEFAULT_FILENAME = "igs20.atx"

# IGS switched its products from ITRF2014 (igs14.atx) to ITRF2020
# (igs20.atx) on this date (methodology §2.1).
IGS20_START = date(2022, 11, 27)


def select_atx_for_date(target: date) -> str:
    """Return the ATX filename appropriate for processing ``target``.

    Per methodology §2.1, data **before** 2022-11-27 uses ``igs14.atx``
    (ITRF2014); **on/after**, ``igs20.atx`` (ITRF2020).

    Only the igs20 branch is implemented — the v1.0.0 evaluation period
    is 2025-04 onward (all igs20). Processing pre-2022-11-27 data
    requires the igs14 branch, a prerequisite for historical backfill
    (Phase 2/3, methodology §8.4) that is **not yet built**. This guard
    raises rather than silently applying igs20 (the wrong frame) to
    pre-switch data.
    """
    if target < IGS20_START:
        raise NotImplementedError(
            f"ATX selection for {target.isoformat()} requires the igs14.atx "
            f"(ITRF2014) branch, not yet implemented. igs14 is a prerequisite "
            f"for pre-2022-11-27 historical backfill (methodology §2.1 / §8.4); "
            f"only the igs20 path (>= 2022-11-27) is built."
        )
    return DEFAULT_FILENAME


def fetch(
    dest_root: Path,
    *,
    url: str = DEFAULT_URL,
    filename: str = DEFAULT_FILENAME,
    overwrite: bool = True,
) -> AcquisitionResult:
    """Download ``igs20.atx`` into ``{dest_root}/aux/igs/{filename}``.

    Defaults to ``overwrite=True`` because the file is updated upstream
    and we want the freshest copy. The previous file's SHA-256 remains
    in ``acquisition.jsonl`` so the history is preserved even though
    the local copy is replaced.
    """
    dest = dest_root / "aux" / "igs" / filename
    return download(
        url,
        dest,
        source=SOURCE,
        metadata={"file": filename},
        overwrite=overwrite,
    )
