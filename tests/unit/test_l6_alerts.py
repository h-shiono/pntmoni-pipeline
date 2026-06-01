"""Tests for L6 broadcast alert extraction/aggregation (§6)."""
from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from pntmoni_pipeline.analysis import _l6_alerts as L

HEADER = (
    "Epoch Time,Preamble,PRN,L6 message type ID,Vender ID,"
    "Message Generation Facility ID and CLAS Transmit Pattern ID,"
    "CLAS Transmit Pattern ID,Subframe indicator,Alert Flag\n"
)
# 4 messages: alerts on prn 193 (tow 316801) and prn 194 (tow 316802).
ROWS = (
    "316800, 0x1a-0xcf-0xfc-0x1d, 193, 177, 5, 2, 0, 1, 0\n"
    "316801, 0x1a-0xcf-0xfc-0x1d, 193, 176, 5, 2, 0, 0, 1\n"
    "316802, 0x1a-0xcf-0xfc-0x1d, 194, 176, 5, 2, 0, 0, 1\n"
    "316803, 0x1a-0xcf-0xfc-0x1d, 193, 176, 5, 2, 0, 0, 0\n"
)


def _fixture(tmp_path: Path) -> Path:
    p = tmp_path / "parse_cssr_header.csv"
    p.write_text(HEADER + ROWS, encoding="utf-8")
    return p


def test_parse_header_csv_columns_and_types(tmp_path):
    df = L.parse_header_csv(_fixture(tmp_path))
    assert list(df.columns) == list(L.RAW_COLUMNS)
    assert len(df) == 4
    assert df["tow"].dtype.kind == "i"
    assert df["prn"].dtype.kind == "i"
    assert df["alert_flag"].tolist() == [0, 1, 1, 0]


def test_tow_to_utc_known_value():
    # 316800 s = 3 d 16 h into the GPS week; 2025-01-22 is a Wednesday.
    # GPST 16:00:00 minus the 18 s GPST-UTC offset = 15:59:42 UTC.
    assert L.tow_to_utc(316800, date(2025, 1, 22)) == datetime(
        2025, 1, 22, 15, 59, 42, tzinfo=UTC
    )


def test_file_events_filters_alerts(tmp_path):
    ev = L.file_events(_fixture(tmp_path), date(2025, 1, 22))
    assert list(ev["prn"]) == [193, 194]
    assert list(ev["tow"]) == [316801, 316802]
    assert ev["time_utc"].iloc[0] == datetime(2025, 1, 22, 15, 59, 43, tzinfo=UTC)


def test_summarize(tmp_path):
    p = _fixture(tmp_path)
    s = L.summarize([(p, date(2025, 1, 22))], period="2025-01")
    assert s.n_messages == 4
    assert s.n_alerts == 2
    assert s.alert_rate == 0.5
    assert s.per_prn == {193: 1, 194: 1}


def test_summarize_empty_when_no_alerts(tmp_path):
    p = tmp_path / "parse_cssr_header.csv"
    p.write_text(HEADER + "316800, x, 193, 176, 5, 2, 0, 0, 0\n", encoding="utf-8")
    s = L.summarize([(p, date(2025, 1, 22))], period="2025-01")
    assert s.n_messages == 1
    assert s.n_alerts == 0
    assert s.alert_rate == 0.0
    assert s.per_prn == {}


def test_cross_reference_outages_matches_prn_and_window(tmp_path):
    ev = L.file_events(_fixture(tmp_path), date(2025, 1, 22))
    outages = pd.DataFrame(
        {
            "event_id": ["NAQU2025-194"],
            "prn": [194],
            "start_at": [datetime(2025, 1, 22, 0, 0, tzinfo=UTC)],
            "end_at": [datetime(2025, 1, 23, 0, 0, tzinfo=UTC)],
        }
    )
    annotated = L.cross_reference_outages(ev, outages)
    by_prn = dict(zip(annotated["prn"], annotated["outage_match"], strict=True))
    assert by_prn[194] == "NAQU2025-194"   # within window
    assert pd.isna(by_prn[193])            # no matching outage


def test_cross_reference_outages_empty_outages(tmp_path):
    ev = L.file_events(_fixture(tmp_path), date(2025, 1, 22))
    annotated = L.cross_reference_outages(ev, pd.DataFrame())
    assert "outage_match" in annotated.columns
    assert annotated["outage_match"].isna().all()


# Duplicate (tow,prn) on prn 193; a distinct prn 194 at the same tow.
DUP_ROWS = (
    "316800, x, 193, 176, 5, 2, 0, 0, 1\n"   # alert, prn 193
    "316800, x, 193, 176, 5, 2, 0, 0, 1\n"   # duplicate (tow,prn) -> dropped
    "316800, x, 194, 176, 5, 2, 0, 0, 1\n"   # same tow, prn 194 -> kept
    "316801, x, 193, 176, 5, 2, 0, 0, 0\n"   # no alert
)


def test_dedup_drops_same_tow_prn_keeps_distinct_prn(tmp_path):
    p = tmp_path / "parse_cssr_header.csv"
    p.write_text(HEADER + DUP_ROWS, encoding="utf-8")
    df = L.dedup_messages(L.parse_header_csv(p))
    # 4 raw rows -> 3 unique (tow,prn): (316800,193),(316800,194),(316801,193)
    assert len(df) == 3
    keys = set(zip(df["tow"], df["prn"], strict=True))
    assert keys == {(316800, 193), (316800, 194), (316801, 193)}


def test_summarize_does_not_double_count_duplicates(tmp_path):
    p = tmp_path / "parse_cssr_header.csv"
    p.write_text(HEADER + DUP_ROWS, encoding="utf-8")
    s = L.summarize([(p, date(2025, 1, 22))], period="2025-01")
    assert s.n_messages == 3        # unique messages, not 4
    assert s.n_duplicates == 1
    assert s.n_alerts == 2          # 193 once (not twice) + 194
    assert s.per_prn == {193: 1, 194: 1}
