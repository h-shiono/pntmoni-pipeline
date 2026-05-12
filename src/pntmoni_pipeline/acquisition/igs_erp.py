"""IGS Earth Rotation Parameters (igu00p01.erp) acquisition.

Fetches the accumulated IGS Ultra-Rapid ERP table from CDDIS and
decompresses the ``.Z`` (LZW) container. Earthdata Login is required;
the underlying download helper handles the cross-origin redirect dance
(see lessons.md ``httpx strips Authorization on cross-origin redirect``).

Provenance is recorded for BOTH the on-wire ``.Z`` artefact and the
uncompressed ``.erp`` we use at runtime so the audit chain is
reproducible.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from ._base import AcquisitionResult, sha256_file, utcnow
from ._http import EARTHDATA_AUTH_HOSTS, download, earthdata_auth
from ._provenance import record as record_provenance

logger = logging.getLogger(__name__)

DEFAULT_URL = "https://cddis.nasa.gov/archive/gnss/products/igu00p01.erp.Z"
SOURCE_COMPRESSED = "igs_erp_z"
SOURCE_UNCOMPRESSED = "igs_erp"
DEFAULT_FILENAME = "igu00p01.erp"
_UNCOMPRESS_BINARY = "/usr/bin/uncompress"


def _uncompress(src_z: Path, dest: Path) -> None:
    """Run ``uncompress`` on ``src_z`` and write the output to ``dest``.

    macOS ``gunzip`` does not support the legacy LZW ``.Z`` format;
    ``/usr/bin/uncompress`` does. We stream stdout to ``dest`` so the
    source ``.Z`` is preserved (re-acquisition is bandwidth-cheap but
    we want both artefacts on disk for audit).
    """
    if not Path(_UNCOMPRESS_BINARY).is_file():
        raise FileNotFoundError(
            f"{_UNCOMPRESS_BINARY} not found — install BSD uncompress (POSIX utility)"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    try:
        with tmp.open("wb") as fp:
            subprocess.run(
                [_UNCOMPRESS_BINARY, "-c", str(src_z)],
                stdout=fp,
                stderr=subprocess.PIPE,
                check=True,
            )
        shutil.move(str(tmp), str(dest))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def fetch(
    dest_root: Path,
    *,
    url: str = DEFAULT_URL,
    filename: str = DEFAULT_FILENAME,
    overwrite: bool = True,
) -> tuple[AcquisitionResult, AcquisitionResult]:
    """Acquire and decompress ``igu00p01.erp.Z``.

    Returns ``(compressed_result, uncompressed_result)``. Both records
    are appended to ``acquisition.jsonl``. Files live under
    ``{dest_root}/aux/igs/``:

    - ``igu00p01.erp.Z`` — on-wire artefact
    - ``igu00p01.erp``   — uncompressed, referenced by rnx2rtkp
    """
    auth = earthdata_auth()
    if auth is None:
        raise RuntimeError(
            "Earthdata credentials required for CDDIS — set "
            "EARTHDATA_USER/EARTHDATA_PASSWORD or configure ~/.netrc"
        )

    dest_z = dest_root / "aux" / "igs" / f"{filename}.Z"
    compressed = download(
        url,
        dest_z,
        source=SOURCE_COMPRESSED,
        auth=auth,
        auth_hosts=EARTHDATA_AUTH_HOSTS,
        metadata={"file": f"{filename}.Z"},
        overwrite=overwrite,
    )

    dest_plain = dest_root / "aux" / "igs" / filename
    _uncompress(dest_z, dest_plain)
    sha = sha256_file(dest_plain)
    uncompressed = AcquisitionResult(
        source=SOURCE_UNCOMPRESSED,
        url=f"derived-from:{url}",
        path=dest_plain,
        sha256=sha,
        size_bytes=dest_plain.stat().st_size,
        retrieved_at=utcnow(),
        skipped=False,
        metadata={
            "file": filename,
            "source_sha256": compressed.sha256,
            "tool": "uncompress",
        },
    )
    record_provenance(uncompressed)
    logger.info(
        "uncompressed %s (%d bytes, sha256=%s)",
        dest_plain.name, uncompressed.size_bytes, sha[:12],
    )
    return compressed, uncompressed
