"""NANU (Notice Advisory to NAVSTAR Users) fetcher.

Source: USCG NAVCEN GPS archive. Each NANU is a plain-text file at:

    https://www.navcen.uscg.gov/sites/default/files/gps/NANU/{YEAR}/{YEAR}{NNN}.nnu

NANUs within a year are numbered sequentially from 001. There is no
authoritative listing endpoint; we enumerate by walking the URL
pattern and detecting 404 as "this number does not exist". A small
gap tolerance handles deleted / withdrawn numbers.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx

from ._models import RawNotice
from ._navstar_format import NavstarParsed, parse as parse_navstar

logger = logging.getLogger(__name__)

DEFAULT_BASE = "https://www.navcen.uscg.gov/sites/default/files/gps/NANU"
DEFAULT_GAP_TOLERANCE = 5     # consecutive 404s before stopping enumeration
DEFAULT_TIMEOUT = 30.0
SOURCE_NAME = "nanu"


def url_for(number: str, *, base: str = DEFAULT_BASE) -> str:
    """Return the URL for a 7-digit NANU number (e.g. ``"2025001"``)."""
    year = number[:4]
    return f"{base}/{year}/{number}.nnu"


def fetch_year(
    year: int,
    *,
    base: str = DEFAULT_BASE,
    start: int = 1,
    end: int | None = None,
    gap_tolerance: int = DEFAULT_GAP_TOLERANCE,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[tuple[RawNotice, NavstarParsed]]:
    """Enumerate NANUs for a given year.

    Stops at ``end`` (inclusive) if provided, otherwise walks until
    ``gap_tolerance`` consecutive 404s are seen.
    """
    fetched: list[tuple[RawNotice, NavstarParsed]] = []
    consecutive_404 = 0
    n = start
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        while True:
            if end is not None and n > end:
                break
            number = f"{year:04d}{n:03d}"
            url = url_for(number, base=base)
            try:
                resp = client.get(url)
            except httpx.HTTPError as e:
                logger.warning("NANU %s fetch error: %s — treating as gap", number, e)
                consecutive_404 += 1
                if consecutive_404 >= gap_tolerance and end is None:
                    break
                n += 1
                continue
            if resp.status_code == 404:
                consecutive_404 += 1
                if consecutive_404 >= gap_tolerance and end is None:
                    logger.info(
                        "NANU year %d: stopping at %s after %d consecutive 404s",
                        year, number, gap_tolerance,
                    )
                    break
                n += 1
                continue
            resp.raise_for_status()
            consecutive_404 = 0

            body = resp.text
            sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
            parsed = parse_navstar(body)
            if parsed is None:
                # GENERAL-type NANUs use a free-text format without DTG /
                # SVN / numbered sections — skip with a clear log entry so
                # operators can audit how many of these the year contained.
                # Tracked as an open issue for events normalisation.
                if "NANU TYPE: GENERAL" in body:
                    logger.info("NANU %s: GENERAL type, skipped (no SVN/window)", number)
                else:
                    logger.warning("NANU %s did not parse — skipping", number)
                n += 1
                continue

            raw = RawNotice(
                notice_id=parsed.notice_id,
                constellation="gps",
                svn=parsed.svn,
                prn=parsed.prn,
                notice_type=parsed.type_label,
                published_at=parsed.dtg,
                effective_at=parsed.start_at,
                expires_at=parsed.stop_at,
                body_text=body,
                source_url=url,
                fetched_at=datetime.now(UTC),
                source_sha256=sha,
                extras={
                    "subject": parsed.subject,
                    "reference_id": parsed.reference_id,
                    "condition": parsed.condition,
                },
            )
            fetched.append((raw, parsed))
            n += 1
    logger.info("NANU year %d: %d notices fetched", year, len(fetched))
    return fetched
