"""Tests for the constellation-status scrapers + aggregator."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from pntmoni_pipeline.acquisition.constellation_status import (
    _aggregate as A,
    galileo,
    gps,
    qzss,
)

FIX = Path(__file__).parent / "fixtures" / "constellation"


def _load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


# --- Schema sanity ---------------------------------------------------

def test_row_schema_keys_include_critical_columns():
    keys = set(A.RowSchema.keys())
    for must in (
        "constellation", "satellite_id", "prn", "status",
        "signals", "notice_id", "source_url",
    ):
        assert must in keys


def test_normalize_status_canonical_mapping():
    assert A.normalize_status("USABLE") == "operational"
    assert A.normalize_status("NOT USABLE") == "unusable"
    assert A.normalize_status("Decommissioned") == "decommissioned"
    assert A.normalize_status("Commissioning") == "commissioning"
    assert A.normalize_status("") == "operational"
    assert A.normalize_status("O") == "operational"


# --- GPS scraper -----------------------------------------------------

def test_gps_parse_returns_full_constellation():
    df = gps.parse(_load("gps_navcen.html"))
    assert 20 <= len(df) <= 40                 # roughly 31 GPS sats
    assert (df["constellation"] == "gps").all()
    # All rows have a PRN (integer)
    assert df["prn"].notna().all()
    # Status set is canonical
    assert set(df["status"]) <= {
        "operational", "outage", "unusable", "decommissioned",
    }
    # satellite_id format e.g. "G16"
    assert df["satellite_id"].str.match(r"^G\d{2}$").all()
    # SVN populated
    assert (df["svn"].str.len() > 0).all()


def test_gps_status_classifies_decommissioning_correctly():
    df = gps.parse(_load("gps_navcen.html"))
    # SVN 43 is the decommissioning entry in the snapshot
    sub = df[df["svn"] == "43"]
    if len(sub):
        assert sub.iloc[0]["status"] == "decommissioned"


# --- QZSS scraper ----------------------------------------------------

def test_qzss_parse_pivots_per_satellite():
    df = qzss.parse(_load("qzs_dod.html"))
    assert len(df) >= 4                        # at least 4 active QZSS sats
    assert (df["constellation"] == "qzs").all()
    # All operational in the snapshot
    assert (df["status"] == "operational").all()
    # PNT PRNs are 194-200 range
    assert df["prn"].between(190, 210).all()
    # signals include L6D for CLAS satellites
    assert df["signals"].str.contains("L6D").any()
    # satellite_id format "J<prn>"
    assert df["satellite_id"].str.match(r"^J\d+$").all()


def test_qzss_signals_dedupe_per_satellite():
    df = qzss.parse(_load("qzs_dod.html"))
    # Signals string should never contain duplicates
    for _, row in df.iterrows():
        sigs = [s.strip() for s in row["signals"].split(",") if s.strip()]
        assert len(sigs) == len(set(sigs))


# --- Galileo scraper -------------------------------------------------

def test_galileo_parse_returns_full_constellation():
    df = galileo.parse(_load("gal_gsc.html"))
    assert 20 <= len(df) <= 40
    assert (df["constellation"] == "gal").all()
    # IDs like E11, E12, ...
    assert df["satellite_id"].str.match(r"^E\d+$").all()
    # SVNs of form GSAT0xxx
    assert df["svn"].str.match(r"^GSAT\d+$").all()
    # Status vocabulary canonical
    assert set(df["status"]) <= {
        "operational", "unusable", "decommissioned",
        "commissioning",
    }


def test_galileo_clock_column_populated():
    df = galileo.parse(_load("gal_gsc.html"))
    assert (df["clock"].isin(["RAFS", "PHM"]) | (df["clock"] == "")).all()
    # At least some have a clock type
    assert (df["clock"].str.len() > 0).sum() >= 10


# --- Aggregator + writer ---------------------------------------------

def test_fetch_all_combines_three_sources():
    def fake_http(url):
        return {
            gps.URL: _load("gps_navcen.html"),
            qzss.URL: _load("qzs_dod.html"),
            galileo.URL: _load("gal_gsc.html"),
        }[url]

    res = A.fetch_all(http_get=fake_http)
    assert res.sources_ok == {"gps": True, "qzs": True, "gal": True}
    assert res.errors == {}
    assert set(res.df["constellation"]) == {"gps", "qzs", "gal"}


def test_fetch_all_continues_when_one_source_fails():
    def fake_http(url):
        if url == galileo.URL:
            raise RuntimeError("network down")
        return {
            gps.URL: _load("gps_navcen.html"),
            qzss.URL: _load("qzs_dod.html"),
        }[url]

    res = A.fetch_all(http_get=fake_http)
    assert res.sources_ok == {"gps": True, "qzs": True, "gal": False}
    assert "gal" in res.errors
    # gps and qzs rows still made it in
    assert set(res.df["constellation"]) == {"gps", "qzs"}


def test_write_snapshot_creates_dated_and_latest(tmp_path: Path):
    def fake_http(url):
        return {
            gps.URL: _load("gps_navcen.html"),
            qzss.URL: _load("qzs_dod.html"),
            galileo.URL: _load("gal_gsc.html"),
        }[url]

    res = A.fetch_all(http_get=fake_http)
    out = tmp_path / "out"
    prov = tmp_path / "provenance.jsonl"
    dated, latest = A.write_snapshot(res, out_root=out, provenance_log=prov)

    assert dated.is_file()
    assert latest.is_file()
    assert prov.is_file()

    # Parquet round-trip preserves shape + adds fetched_at
    df = pd.read_parquet(latest)
    assert len(df) == len(res.df)
    assert "fetched_at" in df.columns

    # Provenance entry recorded
    rec = json.loads(prov.read_text().strip().splitlines()[-1])
    assert rec["kind"] == "constellation_status"
    assert rec["n_satellites"] == len(df)
    assert rec["sources_ok"] == {"gps": True, "qzs": True, "gal": True}
