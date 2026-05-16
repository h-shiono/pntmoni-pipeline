"""Tests for the NANU / NAQU / NAGU parsers.

Fixture data is captured from live upstream responses on 2026-05-16:
NANU 2025001 (USCG), NAQU 2025600 (QSS), NAGU 2026031 (GSC RSS).
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pntmoni_pipeline.acquisition.satellite_outages import _navstar_format, nagu


# ---------------------------------------------------------------------------
# Fixtures (verbatim captures from live upstream)
# ---------------------------------------------------------------------------

NANU_2025001 = """NOTICE ADVISORY TO NAVSTAR USERS (NANU) 2025001
SUBJ: SVN73 (PRN10) FORECAST OUTAGE JDAY 009/0945 - JDAY 009/2145
1.     NANU TYPE: FCSTDV
       NANU NUMBER: 2025001
       NANU DTG: 061932Z JAN 2025
       REFERENCE NANU: N/A
       REF NANU DTG: N/A
       SVN: 73
       PRN: 10
       START JDAY: 009
       START TIME ZULU: 0945
       START CALENDAR DATE: 09 JAN 2025
       STOP JDAY: 009
       STOP TIME ZULU: 2145
       STOP CALENDAR DATE: 09 JAN 2025

2.  CONDITION: GPS SATELLITE SVN73 (PRN10) WILL BE UNUSABLE ON JDAY 009
    (09 JAN 2025) BEGINNING 0945 ZULU UNTIL JDAY 009 (09 JAN 2025)
    ENDING 2145 ZULU.

3.  POC: CIVILIAN - NAVCEN AT 703-313-5900, HTTPS://WWW.NAVCEN.USCG.GOV
"""

NAQU_2025600 = (
    "NOTICE ADVISORY TO QZSS USERS (NAQU) 2025600\r\n"
    "SUBJ: SVN005 (PRN196) UNUSABLE JDAY 360/0105 - JDAY 360/0105\r\n"
    "1.      NAQU TYPE: L6_UNUNOREF\r\n"
    "        NAQU NUMBER: 2025600\r\n"
    "        NAQU DTG: 260925Z DEC 2025\r\n"
    "        REFERENCE NAQU: N/A\r\n"
    "        REF NAQU DTG: N/A\r\n"
    "        SVN: 005\r\n"
    "        PRN: 196\r\n"
    "        START JDAY: 360\r\n"
    "        START TIME ZULU: 0105\r\n"
    "        START CALENDAR DATE: 26 DEC 2025\r\n"
    "        STOP JDAY: 360\r\n"
    "        STOP TIME ZULU: 0105\r\n"
    "        STOP CALENDAR DATE: 26 DEC 2025\r\n"
    "\r\n"
    "2.  CONDITION: QZSS SATELLITE SVN005 (PRN196) WAS UNUSABLE ON JDAY 360\r\n"
    "    (26 DEC 2025) BEGINNING 0105 ZULU UNTIL JDAY 360 (26 DEC 2025)\r\n"
    "    ENDING 0105 ZULU.\r\n"
    "\r\n"
    "3.  POC: - QZSS Services, HTTPS://QZSS.GO.JP/"
)

NAQU_REFERENCED = (  # has a non-N/A REF
    "NOTICE ADVISORY TO QZSS USERS (NAQU) 2025599\r\n"
    "SUBJ: SVN005 (PRN186) UNUSABLE JDAY 360/0114 - JDAY 360/0114\r\n"
    "1.      NAQU TYPE: L1S_UNUSABLE\r\n"
    "        NAQU NUMBER: 2025599\r\n"
    "        NAQU DTG: 260720Z DEC 2025\r\n"
    "        REFERENCE NAQU: 2025581\r\n"
    "        REF NAQU DTG: 260114Z DEC 2025\r\n"
    "        SVN: 005\r\n"
    "        PRN: 186\r\n"
    "        START JDAY: 360\r\n"
    "        START TIME ZULU: 0114\r\n"
    "        START CALENDAR DATE: 26 DEC 2025\r\n"
    "        STOP JDAY: 360\r\n"
    "        STOP TIME ZULU: 0114\r\n"
    "        STOP CALENDAR DATE: 26 DEC 2025\r\n"
    "\r\n"
    "2.  CONDITION: ...\r\n"
    "\r\n"
    "3.  POC: ..."
)

NAGU_2026031_DESC = (
    '&lt;span class="field field--name-title"&gt;NOTICE ADVISORY TO GALILEO USERS (NAGU) 2026031&lt;/span&gt;'
    '&lt;div class="text-formatted"&gt;'
    '&lt;p&gt;DATE GENERATED (UTC): 2026-05-08 09:20&lt;/p&gt;'
    '&lt;p&gt;NAGU TYPE: USABLE&lt;br&gt;'
    'NAGU NUMBER: 2026031&lt;br&gt;'
    'NAGU SUBJECT: USABLE AS FROM 2026-05-08&lt;br&gt;'
    'NAGU REFERENCED TO: &lt;a href="..."&gt;2026030&lt;/a&gt;&lt;br&gt;'
    'START DATE EVENT (UTC): 2026-05-08 08:31&lt;br&gt;'
    'END DATE EVENT (UTC): N/A&lt;br&gt;'
    'SATELLITE AFFECTED: GSAT0219&lt;br&gt;'
    'SPACE VEHICLE ID: 36&lt;br&gt;'
    'SIGNAL(S) AFFECTED: ALL&lt;/p&gt;'
    '&lt;p&gt;EVENT DESCRIPTION: GALILEO SATELLITE GSAT0219 (ALL SIGNALS) IS USABLE SINCE/AS OF 2026-05-08 BEGINNING 08:31 UTC.&lt;/p&gt;'
    '&lt;/div&gt;'
)


# ---------------------------------------------------------------------------
# NAVSTAR / NANU parser
# ---------------------------------------------------------------------------

def test_navstar_parse_nanu_2025001() -> None:
    p = _navstar_format.parse(NANU_2025001)
    assert p is not None
    assert p.notice_id == "NANU 2025001"
    assert p.notice_kind == "NANU"
    assert p.subject == "SVN73 (PRN10) FORECAST OUTAGE JDAY 009/0945 - JDAY 009/2145"
    assert p.type_label == "FCSTDV"
    assert p.number == "2025001"
    assert p.dtg == datetime(2025, 1, 6, 19, 32, tzinfo=UTC)
    assert p.reference_id is None
    assert p.svn == 73
    assert p.prn == 10
    assert p.start_at == datetime(2025, 1, 9, 9, 45, tzinfo=UTC)
    assert p.stop_at == datetime(2025, 1, 9, 21, 45, tzinfo=UTC)
    assert "WILL BE UNUSABLE" in p.condition


def test_navstar_parse_naqu_2025600() -> None:
    p = _navstar_format.parse(NAQU_2025600)
    assert p is not None
    assert p.notice_id == "NAQU 2025600"
    assert p.notice_kind == "NAQU"
    assert p.type_label == "L6_UNUNOREF"
    assert p.dtg == datetime(2025, 12, 26, 9, 25, tzinfo=UTC)
    assert p.svn == 5
    assert p.prn == 196
    # DOY 360 of 2025 = 2025-12-26
    assert p.start_at == datetime(2025, 12, 26, 1, 5, tzinfo=UTC)
    assert p.stop_at == datetime(2025, 12, 26, 1, 5, tzinfo=UTC)


def test_navstar_parse_naqu_with_reference() -> None:
    p = _navstar_format.parse(NAQU_REFERENCED)
    assert p is not None
    assert p.reference_id == "2025581"
    assert p.reference_dtg == datetime(2025, 12, 26, 1, 14, tzinfo=UTC)


def test_navstar_parse_rejects_unknown_format() -> None:
    assert _navstar_format.parse("not a notice") is None
    assert _navstar_format.parse("") is None


# ---------------------------------------------------------------------------
# NAGU parser
# ---------------------------------------------------------------------------

def test_nagu_parse_description() -> None:
    parsed = nagu._parse_description(NAGU_2026031_DESC)
    assert parsed is not None
    assert parsed["nagu_type"] == "USABLE"
    assert parsed["subject"] == "USABLE AS FROM 2026-05-08"
    assert parsed["reference_id"] == "2026030"
    assert parsed["satellite_affected"] == "GSAT0219"
    assert parsed["space_vehicle_id"] == 36
    assert parsed["signals_affected"] == "ALL"
    assert parsed["start_at"] == datetime(2026, 5, 8, 8, 31, tzinfo=UTC)
    assert parsed["end_at"] is None  # N/A


def test_nagu_parse_description_no_kv_returns_none() -> None:
    assert nagu._parse_description("nothing useful") is None


def test_nagu_description_to_plain_text_strips_html() -> None:
    text = nagu._description_to_plain_text(NAGU_2026031_DESC)
    assert "NAGU NUMBER: 2026031" in text
    assert "<br>" not in text
    assert "<p>" not in text
    assert "&lt;" not in text


def test_nagu_parse_rfc822() -> None:
    dt = nagu._parse_rfc822("Tue, 12 May 2026 15:36:58 +0000")
    assert dt == datetime(2026, 5, 12, 15, 36, 58, tzinfo=UTC)


def test_nagu_maybe_int_handles_nan_and_punctuation() -> None:
    assert nagu._maybe_int("N/A") is None
    assert nagu._maybe_int("") is None
    assert nagu._maybe_int("36") == 36
    assert nagu._maybe_int(" 36 ") == 36
