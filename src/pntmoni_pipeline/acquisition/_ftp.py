"""FTP helpers for GSI (terras.gsi.go.jp).

Replaces ``wget --recursive --no-clobber`` with explicit list+download
so callers can filter by station instead of mirroring entire directories.
"""
from __future__ import annotations

import contextlib
import logging
import os
import shutil
from collections.abc import Iterable, Iterator
from ftplib import FTP, error_perm
from pathlib import Path

from ._base import AcquisitionResult, sha256_file, utcnow, with_retry
from ._provenance import record as record_provenance

logger = logging.getLogger(__name__)

GSI_HOST = "terras.gsi.go.jp"


def gsi_credentials() -> tuple[str, str]:
    """Read GSI FTP credentials from env.

    Recognizes ``GSI_FTP_USER``/``GSI_FTP_PASSWORD`` first and falls back
    to ``FTP_USER``/``FTP_PASSWORD`` to match existing shell scripts.
    """
    user = os.environ.get("GSI_FTP_USER") or os.environ.get("FTP_USER")
    pw = os.environ.get("GSI_FTP_PASSWORD") or os.environ.get("FTP_PASSWORD")
    if not user or not pw:
        raise RuntimeError(
            "GSI FTP credentials missing — set GSI_FTP_USER/GSI_FTP_PASSWORD"
        )
    return user, pw


@contextlib.contextmanager
def connect(host: str = GSI_HOST, *, timeout: float = 60.0) -> Iterator[FTP]:
    user, pw = gsi_credentials()
    ftp = FTP(host, timeout=timeout)
    try:
        ftp.login(user=user, passwd=pw)
        yield ftp
    finally:
        with contextlib.suppress(Exception):
            ftp.quit()


def list_dir(ftp: FTP, remote_dir: str) -> list[str]:
    """List filenames in ``remote_dir`` (NLST). Returns [] if missing."""
    try:
        return ftp.nlst(remote_dir)
    except error_perm as e:
        if str(e).startswith("550"):
            return []
        raise


def download_file(
    ftp: FTP,
    remote_path: str,
    dest: Path,
    *,
    source: str,
    metadata: dict | None = None,
    overwrite: bool = False,
    record: bool = True,
) -> AcquisitionResult:
    """Retrieve one file from FTP. Skips if local copy exists."""
    url = f"ftp://{ftp.host}{remote_path if remote_path.startswith('/') else '/' + remote_path}"
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() and not overwrite:
        logger.info("found %s — skipping", dest.name)
        sha = sha256_file(dest)
        result = AcquisitionResult(
            source=source,
            url=url,
            path=dest,
            sha256=sha,
            size_bytes=dest.stat().st_size,
            retrieved_at=utcnow(),
            skipped=True,
            metadata=metadata or {},
        )
        if record:
            record_provenance(result)
        return result

    tmp = dest.with_suffix(dest.suffix + ".partial")

    def _do() -> None:
        with tmp.open("wb") as f:
            ftp.retrbinary(f"RETR {remote_path}", f.write)

    try:
        with_retry(_do, attempts=3, label=f"RETR {remote_path}")
        shutil.move(str(tmp), str(dest))
    except BaseException:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise

    sha = sha256_file(dest)
    result = AcquisitionResult(
        source=source,
        url=url,
        path=dest,
        sha256=sha,
        size_bytes=dest.stat().st_size,
        retrieved_at=utcnow(),
        skipped=False,
        metadata=metadata or {},
    )
    if record:
        record_provenance(result)
    logger.info("downloaded %s (%d bytes)", dest.name, result.size_bytes)
    return result


def filter_by_prefix(
    filenames: Iterable[str],
    prefixes: Iterable[str] | None,
) -> list[str]:
    """Return entries whose basename starts with any of ``prefixes``.

    Used to select specific GEONET stations (4-char IDs) from a directory
    that contains all stations for a given DOY. ``None`` returns all.
    """
    if not prefixes:
        return list(filenames)
    prefset = tuple(prefixes)
    return [
        f for f in filenames
        if Path(f).name.startswith(prefset)
    ]
