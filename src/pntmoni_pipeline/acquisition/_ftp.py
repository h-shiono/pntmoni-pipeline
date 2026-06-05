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
from ftplib import FTP, error_perm, error_proto, error_temp
from pathlib import Path

from ._base import AcquisitionResult, sha256_file, utcnow, with_retry
from ._provenance import record as record_provenance

logger = logging.getLogger(__name__)

GSI_HOST = "terras.gsi.go.jp"

#: Default control/data socket timeout for the GSI FTP server. Bumped from
#: 60 s after observing recurring "cannot read from timed out object" read
#: timeouts mid-batch during ~1300-file daily RINEX pulls.
DEFAULT_TIMEOUT = 120.0

#: Exceptions that mean the FTP connection is dead and must be re-established
#: (vs a permission/path error). Callers downloading many files on one
#: connection should reconnect (see ``reopen``) on these and retry the file.
CONNECTION_ERRORS = (OSError, EOFError, error_temp, error_proto)


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


def open_connection(host: str = GSI_HOST, *, timeout: float = DEFAULT_TIMEOUT) -> FTP:
    """Open and log in a GSI FTP connection. Caller owns its lifecycle.

    Use this (instead of the ``connect`` context manager) when downloading
    many files in a loop that must survive a mid-batch connection death via
    ``reopen``.
    """
    user, pw = gsi_credentials()
    ftp = FTP(host, timeout=timeout)
    ftp.login(user=user, passwd=pw)
    return ftp


def reopen(ftp: FTP | None, host: str = GSI_HOST, *, timeout: float = DEFAULT_TIMEOUT) -> FTP:
    """Close a (possibly dead) connection and return a fresh logged-in one."""
    if ftp is not None:
        with contextlib.suppress(Exception):
            ftp.close()
    return open_connection(host, timeout=timeout)


@contextlib.contextmanager
def connect(host: str = GSI_HOST, *, timeout: float = DEFAULT_TIMEOUT) -> Iterator[FTP]:
    ftp = open_connection(host, timeout=timeout)
    try:
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
