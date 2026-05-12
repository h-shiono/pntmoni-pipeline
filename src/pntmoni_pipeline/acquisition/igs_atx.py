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
from pathlib import Path

from ._base import AcquisitionResult
from ._http import download

logger = logging.getLogger(__name__)

DEFAULT_URL = "https://files.igs.org/pub/station/general/igs20.atx"
SOURCE = "igs_atx"
DEFAULT_FILENAME = "igs20.atx"


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
