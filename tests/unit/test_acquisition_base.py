"""Unit tests for hashing, provenance, and URL composition.

Network-dependent integration tests live elsewhere (marked `integration`).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from pntmoni_pipeline.acquisition import _provenance, sha256_file
from pntmoni_pipeline.acquisition._base import AcquisitionResult, utcnow, with_retry
from pntmoni_pipeline.acquisition import cddis_brdc, geonet_rinex, qzss_l6


def test_sha256_file_known_value(tmp_path: Path) -> None:
    p = tmp_path / "hello.txt"
    p.write_bytes(b"hello\n")
    # `printf 'hello\n' | sha256sum`
    assert sha256_file(p) == (
        "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03"
    )


def test_provenance_record_appends_jsonl(tmp_path: Path) -> None:
    log = tmp_path / "acquisition.jsonl"
    sample = AcquisitionResult(
        source="test",
        url="https://example.com/x",
        path=tmp_path / "x",
        sha256="deadbeef",
        size_bytes=42,
        retrieved_at=utcnow(),
        skipped=False,
        metadata={"k": "v"},
    )
    _provenance.record(sample, path=log)
    _provenance.record(sample, path=log)

    lines = log.read_text().strip().splitlines()
    assert len(lines) == 2
    entry = json.loads(lines[0])
    assert entry["source"] == "test"
    assert entry["sha256"] == "deadbeef"
    assert entry["metadata"] == {"k": "v"}
    assert entry["path"] == str(sample.path)


def test_with_retry_succeeds_after_transient_failure() -> None:
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("nope")
        return "ok"

    result = with_retry(flaky, attempts=3, initial_backoff=0.0, label="flaky")
    assert result == "ok"
    assert calls["n"] == 3


def test_with_retry_reraises_after_exhausting_attempts() -> None:
    def always_fail() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        with_retry(always_fail, attempts=2, initial_backoff=0.0)


def test_geonet_rinex_remote_dir_padding() -> None:
    assert geonet_rinex.remote_dir(2025, 9) == "/data/GRJE_3.02/2025/009"
    assert geonet_rinex.remote_dir(2025, 365) == "/data/GRJE_3.02/2025/365"


def test_cddis_brdc_filename_and_url() -> None:
    d = date(2025, 4, 9)  # DOY 099
    assert cddis_brdc.filename(2025, 99) == (
        "BRDC00IGS_R_20250990000_01D_MN.rnx.gz"
    )
    expected = (
        "https://cddis.nasa.gov/archive/gnss/data/daily/2025/099/25p/"
        "BRDC00IGS_R_20250990000_01D_MN.rnx.gz"
    )
    assert cddis_brdc.url(d.year, 99) == expected


def test_qzss_l6_filenames_and_24_hours() -> None:
    assert len(qzss_l6.HOUR_SUFFIXES) == 24
    assert qzss_l6.HOUR_SUFFIXES[0] == "A"
    assert qzss_l6.HOUR_SUFFIXES[-1] == "X"
    assert qzss_l6.hourly_filename(2025, 99, "A") == "2025099A.l6"
    assert qzss_l6.merged_filename(2025, 99) == "2025099AX.l6"
