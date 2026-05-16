"""NAQU (Notice Advisory to QZSS Users) fetcher.

Source: Cabinet Office Japan / QSS, accessed via the AJAX endpoint
backing https://sys.qzss.go.jp/dod/en/naqu.html. The page is a
JavaScript-driven listing; we replicate the POST that the page makes
to the ``/ajax.do`` endpoint with the year as the year-pager value.

The endpoint returns JSON containing the full body text of each
NAQU in a ``MODAL_TEXT`` field — no per-notice GET is needed.
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

DEFAULT_AJAX_URL = "https://sys.qzss.go.jp/ajax.do"
REFERER = "https://sys.qzss.go.jp/dod/en/naqu.html"
CONDUCTOR_FIX_NO = "DOD_USR_NAQ001J@2"
DEFAULT_TIMEOUT = 60.0
SOURCE_NAME = "naqu"

# All six service-domain flags + four event-group flags are checked on
# upstream by default; we mirror that here so the result covers every
# advertised NAQU.
_DEFAULT_SERVICE_FLAGS = (
    ("DSS_PNT", "on"),
    ("DSS_SLAS", "on"),
    ("DSS_DCR", "on"),
    ("DSS_DCX", "on"),
    ("DSS_CLAS", "on"),
    ("DSS_MDC", "on"),
)
_DEFAULT_GROUP_FLAGS = (
    ("DSG_FO", "on"),
    ("DSG_UO", "on"),
    ("DSG_OTHER", "on"),
    ("DSG_RS", "on"),
)


def fetch_year(
    year: int,
    *,
    ajax_url: str = DEFAULT_AJAX_URL,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[tuple[RawNotice, NavstarParsed]]:
    """Fetch every NAQU for ``year`` by walking the upstream paginator."""
    fetched: list[tuple[RawNotice, NavstarParsed]] = []
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        max_page = _probe_max_page(client, year, ajax_url)
        logger.info("NAQU year %d: %d pages to walk", year, max_page)
        for page in range(1, max_page + 1):
            data = _query_page(client, year, page, ajax_url)
            records = data.get("JSON_CS_LIST") or []
            for rec in records:
                raw_parsed = _record_to_raw(rec)
                if raw_parsed is not None:
                    fetched.append(raw_parsed)
    logger.info("NAQU year %d: %d notices fetched", year, len(fetched))
    return fetched


def _query_page(
    client: httpx.Client,
    year: int,
    page: int,
    ajax_url: str,
) -> dict:
    form: dict[str, str] = {
        "coreAjaxField": "DirectConductor",
        "coreAjaxFixNo": CONDUCTOR_FIX_NO,
        "CURRENT_PAGE": str(year),
        "DATA_CURRENT_PAGE": str(page),
    }
    form.update(dict(_DEFAULT_SERVICE_FLAGS))
    form.update(dict(_DEFAULT_GROUP_FLAGS))
    resp = client.post(
        ajax_url,
        data=form,
        headers={"Referer": REFERER, "X-Requested-With": "XMLHttpRequest"},
    )
    resp.raise_for_status()
    return resp.json()


def _probe_max_page(client: httpx.Client, year: int, ajax_url: str) -> int:
    """First call → discover RECODE_COUNT / MAX_PAGE."""
    data = _query_page(client, year, 1, ajax_url)
    page_info = data.get("JSON_CS_PAGING") or [{}]
    max_page = int(page_info[0].get("DATA_MAX_PAGE", "1"))
    return max_page


def _record_to_raw(
    rec: dict,
) -> tuple[RawNotice, NavstarParsed] | None:
    body = rec.get("MODAL_TEXT") or ""
    if not body:
        return None
    parsed = parse_navstar(body)
    if parsed is None:
        logger.warning("NAQU record did not parse: number=%s", rec.get("NAQ_NAQU_NUMBER"))
        return None

    # Upstream tags each record with NAQ_TYPE (e.g. "UNUNOREF") and
    # NAQ_SS_SIGNAL (e.g. "L6", "L1S", "PNT"). The parsed body's
    # `type_label` is the prefixed form (e.g. "L6_UNUNOREF") which is
    # more informative; we keep the AJAX hints in extras.
    signal = rec.get("NAQ_SS_SIGNAL")
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return (
        RawNotice(
            notice_id=parsed.notice_id,
            constellation="qzs",
            svn=parsed.svn,
            prn=parsed.prn,
            notice_type=parsed.type_label,
            published_at=parsed.dtg,
            effective_at=parsed.start_at,
            expires_at=parsed.stop_at,
            body_text=body,
            source_url=f"https://sys.qzss.go.jp/dod/en/naqu.html#{parsed.number}",
            fetched_at=datetime.now(UTC),
            source_sha256=sha,
            extras={
                "subject": parsed.subject,
                "reference_id": parsed.reference_id,
                "condition": parsed.condition,
                "naq_ss_signal": signal,
                "naq_create_datetime": rec.get("NAQ_CREATE_DATETIME"),
            },
        ),
        parsed,
    )
