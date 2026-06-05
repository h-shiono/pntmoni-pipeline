"""Unit tests for geonet_rinex.fetch FTP reconnect resilience.

A single long-lived FTP connection can die mid-batch (read timeout) during
a ~1300-file daily RINEX pull. fetch must reconnect and retry the failing
file instead of aborting the whole day.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from pntmoni_pipeline.acquisition import geonet_rinex


def _patch_common(monkeypatch, entries):
    """Patch list_dir + connection factory; return a call recorder."""
    rec = {"reopens": 0}
    monkeypatch.setattr(geonet_rinex, "list_dir", lambda ftp, rdir: entries)
    monkeypatch.setattr(geonet_rinex, "open_connection", lambda *a, **k: object())

    def fake_reopen(ftp, *a, **k):
        rec["reopens"] += 1
        return object()

    monkeypatch.setattr(geonet_rinex, "reopen", fake_reopen)
    return rec


def _result(name: str):
    from pntmoni_pipeline.acquisition._base import AcquisitionResult, utcnow

    return AcquisitionResult(
        source="geonet_rinex", url="ftp://x/" + name, path=Path(name),
        sha256="0" * 64, size_bytes=1, retrieved_at=utcnow(),
        skipped=False, metadata={},
    )


def test_fetch_reconnects_on_connection_death(monkeypatch, tmp_path):
    entries = ["00011210.26o.gz", "00021210.26o.gz"]
    rec = _patch_common(monkeypatch, entries)

    calls = {"n": 0}

    def flaky_download(ftp, remote_path, dest, **kw):
        calls["n"] += 1
        # First file's first attempt dies; everything else succeeds.
        if calls["n"] == 1:
            raise OSError("cannot read from timed out object")
        return _result(Path(remote_path).name)

    monkeypatch.setattr(geonet_rinex, "download_file", flaky_download)

    results = geonet_rinex.fetch(date(2026, 5, 1), tmp_path)
    assert len(results) == 2          # both files ultimately downloaded
    assert rec["reopens"] == 1        # reconnected exactly once
    assert calls["n"] == 3            # file1 (fail, retry), file2


def test_fetch_skips_file_after_persistent_failure(monkeypatch, tmp_path):
    entries = ["00011210.26o.gz", "00021210.26o.gz"]
    rec = _patch_common(monkeypatch, entries)

    def download(ftp, remote_path, dest, **kw):
        if Path(remote_path).name.startswith("0001"):
            raise OSError("dead")          # never recovers
        return _result(Path(remote_path).name)

    monkeypatch.setattr(geonet_rinex, "download_file", download)

    results = geonet_rinex.fetch(date(2026, 5, 1), tmp_path)
    # file1 skipped after exhausting reconnect attempts; file2 still fetched —
    # the day is NOT aborted by one bad file.
    assert len(results) == 1
    assert results[0].path.name.startswith("0002")
    assert rec["reopens"] == geonet_rinex.FILE_RECONNECT_ATTEMPTS - 1
