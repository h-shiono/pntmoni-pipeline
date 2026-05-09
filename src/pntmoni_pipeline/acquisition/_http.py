"""HTTPS download helper with streaming, idempotency, and provenance.

Earthdata / CDDIS specifics
---------------------------
CDDIS issues a 302 to ``urs.earthdata.nasa.gov`` for OAuth, which
challenges Basic Auth and then sets a session cookie. ``httpx`` strips
the ``Authorization`` header on cross-origin redirects (a security
default), so the standard ``follow_redirects=True`` flow never gets
authenticated. We solve this with manual redirect handling that
applies Basic Auth only when the redirect target is in
``auth_hosts``; cookies are persisted across the chain via a single
``httpx.Client``. We also guard against the silent failure mode where
HTML (login page) ends up written to disk.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

import httpx

from ._base import AcquisitionResult, sha256_file, utcnow, with_retry
from ._provenance import record as record_provenance

logger = logging.getLogger(__name__)

_HTML_PREFIXES = (b"<!DOCTYPE html", b"<html", b"<!doctype html", b"<HTML")
_DEFAULT_MAX_REDIRECTS = 10
EARTHDATA_AUTH_HOSTS = frozenset({"urs.earthdata.nasa.gov"})


def _looks_like_html(path: Path, peek_bytes: int = 256) -> bool:
    try:
        with path.open("rb") as f:
            head = f.read(peek_bytes).lstrip()
    except OSError:
        return False
    return any(head.startswith(p) for p in _HTML_PREFIXES)


def _stream_to_file(
    client: httpx.Client,
    url: str | httpx.URL,
    dest: Path,
    *,
    auth: httpx.BasicAuth | None,
    auth_hosts: frozenset[str] | None,
    max_redirects: int,
) -> None:
    """Walk redirect chain manually, applying ``auth`` only on ``auth_hosts``.

    Cookies set by intermediate hops are retained on ``client`` for the
    final request that delivers file bytes.
    """
    next_url: httpx.URL = httpx.URL(url) if isinstance(url, str) else url
    for _ in range(max_redirects):
        request_auth: httpx.Auth | None = None
        if auth is not None and (auth_hosts is None or next_url.host in auth_hosts):
            request_auth = auth

        with client.stream("GET", next_url, auth=request_auth) as resp:
            if resp.is_redirect:
                location = resp.headers.get("Location")
                if not location:
                    resp.raise_for_status()
                    return
                next_url = next_url.join(location)
                continue
            resp.raise_for_status()
            with dest.open("wb") as f:
                for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                    f.write(chunk)
            return
    raise RuntimeError(f"too many redirects fetching {url}")


def download(
    url: str,
    dest: Path,
    *,
    source: str,
    auth: tuple[str, str] | None = None,
    auth_hosts: frozenset[str] | None = None,
    metadata: dict | None = None,
    timeout: float = 60.0,
    attempts: int = 3,
    overwrite: bool = False,
    record: bool = True,
    expect_binary: bool = True,
) -> AcquisitionResult:
    """Stream-download ``url`` to ``dest``.

    Atomic via ``.partial`` swap. Skips if the destination already
    exists and ``overwrite`` is False (matches the legacy shell scripts'
    ``--no-clobber`` behaviour).

    Parameters
    ----------
    auth : optional ``(user, password)`` tuple.
    auth_hosts : optional set of hostnames where ``auth`` is applied.
        ``None`` (default) means apply auth to every hop, including the
        initial ``url``. Set to e.g. ``EARTHDATA_AUTH_HOSTS`` for CDDIS
        downloads — auth is then sent only on the URS hop, never on
        ``cddis.nasa.gov`` itself.
    expect_binary : reject downloads that look like an HTML error/login
        page (silent auth failure). Disable for endpoints that legitimately
        serve HTML.
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
    httpx_auth = httpx.BasicAuth(*auth) if auth else None

    def _do_download() -> None:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            _stream_to_file(
                client,
                url,
                tmp,
                auth=httpx_auth,
                auth_hosts=auth_hosts,
                max_redirects=_DEFAULT_MAX_REDIRECTS,
            )

    try:
        with_retry(
            _do_download,
            attempts=attempts,
            retry_on=(httpx.HTTPError, OSError),
            label=f"GET {url}",
        )
        if expect_binary and _looks_like_html(tmp):
            tmp.unlink(missing_ok=True)
            raise RuntimeError(
                f"download saved an HTML page (likely auth/redirect failure) for {url}"
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
