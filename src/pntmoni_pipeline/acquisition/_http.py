"""HTTPS download helper with streaming, idempotency, and provenance."""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

import httpx

from ._base import AcquisitionResult, sha256_file, utcnow, with_retry
from ._provenance import record as record_provenance

logger = logging.getLogger(__name__)


def download(
    url: str,
    dest: Path,
    *,
    source: str,
    auth: tuple[str, str] | None = None,
    metadata: dict | None = None,
    timeout: float = 60.0,
    attempts: int = 3,
    overwrite: bool = False,
    record: bool = True,
) -> AcquisitionResult:
    """Stream-download ``url`` to ``dest``.

    Skips if ``dest`` exists and ``overwrite`` is False (matches the
    shell scripts' "no-clobber" behavior). Atomic via .partial swap.
    """
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

    def _do_download() -> None:
        with httpx.stream(
            "GET", url, auth=auth, timeout=timeout, follow_redirects=True,
        ) as resp:
            resp.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                    f.write(chunk)

    try:
        with_retry(
            _do_download,
            attempts=attempts,
            retry_on=(httpx.HTTPError, OSError),
            label=f"GET {url}",
        )
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


def earthdata_auth() -> tuple[str, str] | None:
    """Resolve CDDIS / Earthdata credentials.

    Order: env vars ``EARTHDATA_USER``/``EARTHDATA_PASSWORD``, then
    ``.netrc`` entry for ``urs.earthdata.nasa.gov``.
    """
    user = os.environ.get("EARTHDATA_USER")
    pw = os.environ.get("EARTHDATA_PASSWORD")
    if user and pw:
        return user, pw

    try:
        import netrc
        n = netrc.netrc()
    except (FileNotFoundError, OSError):
        return None
    for host in ("urs.earthdata.nasa.gov", "cddis.nasa.gov"):
        creds = n.authenticators(host)
        if creds:
            login, _, password = creds
            if login and password:
                return login, password
    return None
