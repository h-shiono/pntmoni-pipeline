"""Unit tests for processing run-summary statistics."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pntmoni_pipeline.processing._base import ProcessingResult
from pntmoni_pipeline.processing._stats import (
    format_summary,
    percentile,
    record,
    summarize,
)


def _result(
    station: str,
    duration_sec: float,
    *,
    skipped: bool = False,
    started_at: datetime | None = None,
) -> ProcessingResult:
    started = started_at or datetime(2026, 4, 1, tzinfo=UTC)
    return ProcessingResult(
        engine="claslib",
        engine_version="082",
        mode="kinematic_p30",
        config_hash="0" * 64,
        station=station,
        date="2026-04-01",
        pos_path=Path(f"data/processed/kinematic_p30/2026/091/{station}0910.pos"),
        trace_path=None,
        config_path=None,
        started_at=started,
        finished_at=started + timedelta(seconds=duration_sec),
        duration_sec=duration_sec,
        skipped=skipped,
    )


def test_percentile_basic() -> None:
    data = [1, 2, 3, 4, 5]
    assert percentile(data, 0) == 1
    assert percentile(data, 50) == 3
    assert percentile(data, 100) == 5


def test_percentile_interpolation() -> None:
    # Linear interpolation between sorted values.
    assert percentile([10, 20], 50) == 15.0
    assert percentile([10, 20, 30, 40], 25) == 17.5  # halfway between 10 and 20+(.75*10)? recompute:
    # k = (4-1) * 25 / 100 = 0.75 → s[0] * 0.25 + s[1] * 0.75 = 10*0.25 + 20*0.75 = 17.5 ✓


def test_percentile_empty_returns_zero() -> None:
    assert percentile([], 50) == 0.0
    assert percentile([], 95) == 0.0


def test_summarize_counts_succeed_skip_fail() -> None:
    started = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
    finished = datetime(2026, 4, 1, 0, 5, 0, tzinfo=UTC)  # 5 minutes wall
    results = [
        _result("0231", 30.0),
        _result("0232", 40.0),
        _result("0233", 50.0, skipped=True),
    ]
    summary = summarize(
        results,
        failed_stations=["9999"],
        started_at=started, finished_at=finished,
        engine="claslib", engine_version="082",
        mode="kinematic_p30", date_iso="2026-04-01",
    )
    assert summary.n_stations == 4              # 2 ok + 1 skipped + 1 failed
    assert summary.n_succeeded == 2
    assert summary.n_skipped == 1
    assert summary.n_failed == 1
    assert summary.failed_stations == ["9999"]
    assert summary.wall_sec == 300.0            # 5 min
    assert summary.duration_total_sec == 70.0   # 30 + 40 (skipped excluded)
    assert summary.duration_p50_sec == 35.0     # halfway between 30 and 40
    assert summary.duration_p95_sec == 39.5     # k=0.95 between 30 and 40 → 30*.05+40*.95
    assert summary.engine == "claslib"
    assert summary.engine_version == "082"


def test_summarize_empty_results_safe() -> None:
    started = datetime(2026, 4, 1, tzinfo=UTC)
    finished = started + timedelta(seconds=1)
    summary = summarize(
        [], failed_stations=[],
        started_at=started, finished_at=finished,
        engine="claslib", engine_version="082",
        mode="kinematic_p30", date_iso="2026-04-01",
    )
    assert summary.n_stations == 0
    assert summary.n_succeeded == 0
    assert summary.duration_p50_sec == 0.0
    assert summary.duration_p95_sec == 0.0
    assert summary.duration_total_sec == 0.0


def test_record_appends_jsonl(tmp_path: Path) -> None:
    started = datetime(2026, 4, 1, tzinfo=UTC)
    finished = started + timedelta(seconds=300)
    summary = summarize(
        [_result("0231", 30.0)],
        failed_stations=[],
        started_at=started, finished_at=finished,
        engine="claslib", engine_version="082",
        mode="kinematic_p30", date_iso="2026-04-01",
    )
    log = tmp_path / "processing.jsonl"
    record(summary, path=log)
    record(summary, path=log)

    lines = log.read_text().strip().splitlines()
    assert len(lines) == 2
    e = json.loads(lines[0])
    assert e["mode"] == "kinematic_p30"
    assert e["engine"] == "claslib"
    assert e["date"] == "2026-04-01"
    assert e["n_succeeded"] == 1
    assert e["wall_sec"] == 300.0
    assert e["duration_total_sec"] == 30.0
    assert isinstance(e["started_at"], str)
    assert e["started_at"].startswith("2026-04-01")


def test_format_summary_includes_key_fields() -> None:
    started = datetime(2026, 4, 1, tzinfo=UTC)
    finished = started + timedelta(seconds=120)
    summary = summarize(
        [_result("0231", 30.0), _result("0232", 35.0)],
        failed_stations=["0233"],
        started_at=started, finished_at=finished,
        engine="claslib", engine_version="082",
        mode="kinematic_p30", date_iso="2026-04-01",
    )
    rendered = format_summary(summary)
    assert "Processed 3 station(s)" in rendered
    assert "succeeded : 2" in rendered
    assert "failed    : 1" in rendered
    assert "0233" in rendered
    assert "Wall time" in rendered
    assert "Parallelism" in rendered  # 2 results / 120s wall → speedup line shown


def test_format_summary_long_failure_list_truncates() -> None:
    started = datetime(2026, 4, 1, tzinfo=UTC)
    finished = started + timedelta(seconds=10)
    summary = summarize(
        [], failed_stations=[f"X{i:03d}" for i in range(20)],
        started_at=started, finished_at=finished,
        engine="claslib", engine_version="082",
        mode="kinematic_p30", date_iso="2026-04-01",
    )
    rendered = format_summary(summary)
    assert "X000" in rendered
    assert "X004" in rendered
    assert "+15 more" in rendered
    # Tail should not be rendered inline (>5 elements truncated)
    assert "X019" not in rendered
