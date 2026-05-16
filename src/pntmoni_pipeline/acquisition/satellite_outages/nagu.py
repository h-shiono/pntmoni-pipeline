"""NAGU (Notice Advisory to Galileo Users) fetcher.

Source: EUSPA / European GNSS Service Centre.

Two ingestion paths:

- **RSS feed** (default for incremental refresh): the GSC publishes a
  channel-level RSS at ``https://www.gsc-europa.eu/rss.xml`` that
  includes recent NAGUs alongside non-NAGU news items. We filter by
  title and extract NAGU fields directly from the HTML-encoded
  ``<description>`` payload — the description already contains every
  field we need (NAGU TYPE, NUMBER, SUBJECT, START/END DATE, SAT, SVN,
  SIGNALS, DESCRIPTION).

- **Per-NAGU .txt** fallback / verification:
  ``https://www.gsc-europa.eu/sites/default/files/NOTICE_ADVISORY_TO_GALILEO_USERS_NAGU_{NUMBER}.txt``.
  Used when an RSS description appears incomplete or for historical
  backfill keyed by known NAGU numbers.

The NAGU body format is *different* from NANU/NAQU: no numbered
sections, instead a list of ``FIELD: value`` lines plus a free-text
description paragraph. We parse it directly in this module.
"""
from __future__ import annotations

import hashlib
import html
import logging
import re
from datetime import UTC, datetime
from xml.etree import ElementTree as ET

import httpx

from ._models import RawNotice

logger = logging.getLogger(__name__)

DEFAULT_RSS_URL = "https://www.gsc-europa.eu/rss.xml"
DEFAULT_TXT_BASE = "https://www.gsc-europa.eu/sites/default/files"
DEFAULT_TIMEOUT = 30.0
SOURCE_NAME = "nagu"

# Title format: "NOTICE ADVISORY TO GALILEO USERS (NAGU) 2026032"
_TITLE_RE = re.compile(r"NOTICE ADVISORY TO GALILEO USERS \(NAGU\)\s+(\d{7})")

# Key-value lines inside the description HTML, format "KEY: value<br>".
# Value can contain inner HTML (e.g. <a href="...">2026030</a> for
# "NAGU REFERENCED TO:"), so we match anything up to the next <br> or
# </p> regardless of internal tags.
_KV_RE = re.compile(
    r"([A-Z][A-Z0-9 ()/]*?):\s*(.+?)(?:<br\s*/?>|</p>)",
    re.IGNORECASE | re.DOTALL,
)


def fetch_recent(
    *,
    rss_url: str = DEFAULT_RSS_URL,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[RawNotice]:
    """Fetch NAGUs surfaced by the GSC RSS feed (recent only)."""
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(rss_url)
        resp.raise_for_status()
        rss_bytes = resp.content

    root = ET.fromstring(rss_bytes)
    items = root.findall(".//item")
    fetched: list[RawNotice] = []
    for item in items:
        title_el = item.find("title")
        if title_el is None or title_el.text is None:
            continue
        m = _TITLE_RE.match(title_el.text.strip())
        if m is None:
            continue
        number = m.group(1)
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        description_html = item.findtext("description") or ""

        parsed = _parse_description(description_html)
        if parsed is None:
            logger.warning("NAGU %s: description parse failed — skipping", number)
            continue

        published_at = _parse_rfc822(pub_date)
        body = _description_to_plain_text(description_html)
        sha = hashlib.sha256(body.encode("utf-8")).hexdigest()

        fetched.append(
            RawNotice(
                notice_id=f"NAGU {number}",
                constellation="gal",
                svn=parsed.get("space_vehicle_id"),
                prn=None,  # Galileo doesn't use PRN naming
                notice_type=parsed.get("nagu_type", ""),
                published_at=published_at or datetime.now(UTC),
                effective_at=parsed.get("start_at"),
                expires_at=parsed.get("end_at"),
                body_text=body,
                source_url=link,
                fetched_at=datetime.now(UTC),
                source_sha256=sha,
                extras={
                    "subject": parsed.get("subject", ""),
                    "reference_id": parsed.get("reference_id"),
                    "satellite_affected": parsed.get("satellite_affected"),
                    "signals_affected": parsed.get("signals_affected"),
                    "event_description": parsed.get("event_description"),
                },
            )
        )
    logger.info("NAGU RSS: %d notices fetched", len(fetched))
    return fetched


def url_for_txt(number: str, *, base: str = DEFAULT_TXT_BASE) -> str:
    return f"{base}/NOTICE_ADVISORY_TO_GALILEO_USERS_NAGU_{number}.txt"


def _description_to_plain_text(description_html: str) -> str:
    """Best-effort: strip HTML for body_text storage."""
    text = html.unescape(description_html)
    # Replace <br>, </p> with newlines, drop other tags.
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</?p[^>]*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _parse_description(description_html: str) -> dict | None:
    """Pull NAGU fields out of the HTML-encoded description blob."""
    unescaped = html.unescape(description_html)
    fields: dict[str, str] = {}
    for m in _KV_RE.finditer(unescaped):
        key = re.sub(r"\s+", "_", m.group(1).strip().lower())
        key = re.sub(r"[()/]", "", key)
        value = m.group(2).strip()
        # Strip inline HTML tags from the value (anchor links etc.).
        value = re.sub(r"<[^>]+>", "", value).strip()
        fields.setdefault(key, value)

    if "nagu_number" not in fields:
        return None

    out: dict = {
        "nagu_type": fields.get("nagu_type", ""),
        "subject": fields.get("nagu_subject", ""),
        "reference_id": _maybe_none(fields.get("nagu_referenced_to", "")),
        "satellite_affected": fields.get("satellite_affected"),
        "signals_affected": fields.get("signals_affected") or fields.get("signal_affected") or None,
        "event_description": fields.get("event_description"),
        "space_vehicle_id": _maybe_int(fields.get("space_vehicle_id", "")),
        "start_at": _parse_event_date(fields.get("start_date_event_utc", "")),
        "end_at": _parse_event_date(fields.get("end_date_event_utc", "")),
    }
    return out


def _maybe_int(s: str) -> int | None:
    s = s.strip()
    if not s or s.upper() == "N/A":
        return None
    # Trim trailing punctuation that may leak from HTML stripping.
    s = re.sub(r"[^\d-]", "", s)
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _maybe_none(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    if not s or s.upper() == "N/A":
        return None
    # Reference values come through as concatenated number text from HTML
    # anchors (e.g. "20260152026017..."); take only the first 7-digit block.
    m = re.search(r"\d{7}", s)
    return m.group(0) if m else s


def _parse_event_date(s: str) -> datetime | None:
    """Parse ``YYYY-MM-DD HH:MM`` (UTC) tokens used in NAGU descriptions."""
    if not s:
        return None
    s = s.strip()
    if s.upper() == "N/A":
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _parse_rfc822(s: str) -> datetime | None:
    """Parse RFC-822 dates from RSS pubDate."""
    if not s:
        return None
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except (TypeError, ValueError):
        return None
