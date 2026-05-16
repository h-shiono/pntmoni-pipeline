"""Parser for the shared NANU / NAQU body format.

Both USCG NAVCEN's NANU and Cabinet Office Japan's NAQU use a
"NOTICE ADVISORY TO {NAVSTAR|QZSS} USERS" body grammar with the same
structure:

    NOTICE ADVISORY TO {CONST} USERS ({TYPE}) {NUMBER}
    SUBJ: <subject line>
    1.     NANU TYPE: <type>
           NANU NUMBER: <number>
           NANU DTG: <DDHHMM>Z MON YYYY
           REFERENCE NANU: <referenced number or N/A>
           REF NANU DTG: <referenced DTG or N/A>
           SVN: <int>
           PRN: <int>
           START JDAY: <DOY>
           START TIME ZULU: <HHMM>
           START CALENDAR DATE: <DD MON YYYY>
           STOP JDAY: <DOY>
           STOP TIME ZULU: <HHMM>
           STOP CALENDAR DATE: <DD MON YYYY>

    2.  CONDITION: <free text>

    3.  POC: <contact info>

NAQU uses the NAQU keyword in place of NANU. The grammar is otherwise
identical. This module parses both into a :class:`NavstarParsed`
record that downstream code maps onto :class:`_models.RawNotice` and
:class:`_models.OutageEvent`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

# DTG (Date-Time Group) format: "DDHHMM<TZ> MON YYYY", e.g. "061932Z JAN 2025"
_DTG_RE = re.compile(
    r"(\d{2})(\d{2})(\d{2})Z\s+([A-Z]{3})\s+(\d{4})"
)
_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


@dataclass(frozen=True)
class NavstarParsed:
    notice_id: str
    notice_kind: Literal["NANU", "NAQU"]
    subject: str
    type_label: str           # NANU TYPE / NAQU TYPE (e.g. "FCSTDV", "L6_UNUNOREF")
    number: str               # 7-digit YYYYNNN
    dtg: datetime             # UTC publication
    reference_id: str | None  # referenced NANU/NAQU number or None
    reference_dtg: datetime | None
    svn: int | None
    prn: int | None
    start_at: datetime | None
    stop_at: datetime | None
    condition: str            # free-text section 2 body
    poc: str                  # free-text section 3 body


def _parse_dtg(s: str) -> datetime | None:
    """Parse a DTG token like ``061932Z JAN 2025`` to UTC datetime."""
    m = _DTG_RE.search(s)
    if m is None:
        return None
    day, hh, mm, mon, yyyy = m.groups()
    month = _MONTHS.get(mon.upper())
    if month is None:
        return None
    try:
        return datetime(int(yyyy), month, int(day), int(hh), int(mm), tzinfo=UTC)
    except ValueError:
        return None


def _parse_jday_time(year: int, jday: str, hhmm: str) -> datetime | None:
    """Parse year-relative JDAY (DOY) + HHMM Zulu → UTC datetime."""
    try:
        doy = int(jday)
        hh = int(hhmm[:2])
        mm = int(hhmm[2:4]) if len(hhmm) >= 4 else 0
    except (ValueError, IndexError):
        return None
    if not (1 <= doy <= 366):
        return None
    try:
        return datetime.strptime(f"{year} {doy:03d}", "%Y %j").replace(
            hour=hh, minute=mm, tzinfo=UTC,
        )
    except ValueError:
        return None


def _maybe_int(s: str) -> int | None:
    s = s.strip()
    if not s or s.upper() == "N/A":
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _maybe_str(s: str) -> str | None:
    s = s.strip()
    if not s or s.upper() == "N/A":
        return None
    return s


def parse(body: str) -> NavstarParsed | None:
    """Parse a NANU- or NAQU-format body. Return None if grammar mismatch.

    Tolerates leading whitespace and trailing whitespace differences.
    Robust to either ``NANU`` or ``NAQU`` keyword throughout.
    """
    # Normalize line endings — upstream NAQU JSON uses CRLF, NANU is LF.
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.splitlines()
    if not lines:
        return None

    header = lines[0].strip()
    m_header = re.match(
        r"NOTICE ADVISORY TO (NAVSTAR|QZSS) USERS\s*\((NANU|NAQU)\)\s+(\d{7})",
        header,
    )
    if m_header is None:
        return None
    notice_kind = m_header.group(2)  # "NANU" or "NAQU"
    number = m_header.group(3)
    notice_id = f"{notice_kind} {number}"  # canonical form with space separator

    # Extract key:value lines. Keys include the NANU/NAQU prefix
    # ("NANU TYPE", "NAQU NUMBER") or stand alone ("SVN", "START JDAY").
    # We don't anchor to start-of-line: the numbered section markers
    # ("1.     ", "2.  ") and indentation vary, but every "KEY: value"
    # pair fits the same anywhere-in-the-line pattern.
    kv_re = re.compile(r"([A-Z][A-Z0-9 /]+?):\s+([^\n]+)")
    raw_kv: dict[str, str] = {}
    for m in kv_re.finditer(text):
        key = m.group(1).strip()
        value = m.group(2).strip()
        # First occurrence wins (Section-1 fields appear before Sections 2/3
        # body text that may incidentally contain colon-bearing tokens).
        raw_kv.setdefault(key, value)

    # Subject
    subject = ""
    for ln in lines:
        if ln.startswith("SUBJ:"):
            subject = ln[len("SUBJ:"):].strip()
            break

    type_label = (
        raw_kv.get("NANU TYPE")
        or raw_kv.get("NAQU TYPE")
        or ""
    )

    # DTG
    dtg_str = raw_kv.get("NANU DTG") or raw_kv.get("NAQU DTG") or ""
    dtg = _parse_dtg(dtg_str)
    if dtg is None:
        return None

    ref_id = _maybe_str(
        raw_kv.get("REFERENCE NANU") or raw_kv.get("REFERENCE NAQU") or ""
    )
    ref_dtg_str = raw_kv.get("REF NANU DTG") or raw_kv.get("REF NAQU DTG") or ""
    ref_dtg = _parse_dtg(ref_dtg_str)

    svn = _maybe_int(raw_kv.get("SVN", ""))
    prn = _maybe_int(raw_kv.get("PRN", ""))

    year = dtg.year
    start_at = _parse_jday_time(
        year,
        raw_kv.get("START JDAY", ""),
        raw_kv.get("START TIME ZULU", ""),
    )
    stop_at = _parse_jday_time(
        year,
        raw_kv.get("STOP JDAY", ""),
        raw_kv.get("STOP TIME ZULU", ""),
    )

    # Section 2 / 3 free text. We split on numbered section markers.
    condition = _extract_section(text, "2.")
    poc = _extract_section(text, "3.")

    return NavstarParsed(
        notice_id=notice_id,
        notice_kind=notice_kind,  # type: ignore[arg-type]
        subject=subject,
        type_label=type_label,
        number=number,
        dtg=dtg,
        reference_id=ref_id,
        reference_dtg=ref_dtg,
        svn=svn,
        prn=prn,
        start_at=start_at,
        stop_at=stop_at,
        condition=condition,
        poc=poc,
    )


def _extract_section(text: str, marker: str) -> str:
    """Extract the body of a numbered section ``N.``.

    Section bodies in NANU/NAQU files start with ``2.``  or ``3.`` and
    run to the next numbered section or end-of-file.
    """
    # Find the section header line.
    idx = text.find(f"\n{marker}")
    if idx < 0:
        idx = 0 if text.startswith(marker) else -1
    if idx < 0:
        return ""
    start = idx if text[idx:].startswith(marker) else idx + 1

    # End is the next numbered section header (^N.).
    end_re = re.compile(r"^\d+\.\s", re.MULTILINE)
    next_match = None
    for m in end_re.finditer(text, pos=start + len(marker)):
        next_match = m
        break

    body = text[start:next_match.start()] if next_match else text[start:]
    # Strip the leading "N. " marker.
    body = re.sub(r"^\d+\.\s*", "", body, count=1).strip()
    return body
