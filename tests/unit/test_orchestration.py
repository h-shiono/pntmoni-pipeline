"""Unit tests for the daily / backfill orchestration drivers.

The engine entrypoints (acquire/process/qc) are network- and binary-bound,
so these tests monkeypatch the ``_steps`` callables with canned
``StepResult`` outcomes and assert the driver's sequencing, dependency
gating, idempotent short-circuit, status rollup, and continue-on-error.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from pntmoni_pipeline.orchestration import _steps, backfill, daily
from pntmoni_pipeline.orchestration._steps import StepResult, status_from_counts


# ---------------------------------------------------------------------------
# status_from_counts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "total,ok,skipped,failed,expected",
    [
        (0, 0, 0, 0, "failed"),       # nothing attempted
        (10, 0, 10, 0, "skipped"),    # all already present
        (10, 10, 0, 0, "ok"),
        (10, 7, 3, 0, "ok"),          # ok + skipped, no failures
        (10, 0, 0, 10, "failed"),     # everything failed
        (10, 6, 0, 4, "partial"),     # mixed
        (10, 0, 5, 5, "partial"),     # some skipped, some failed
    ],
)
def test_status_from_counts(total, ok, skipped, failed, expected):
    assert status_from_counts(total, ok, skipped, failed) == expected


# ---------------------------------------------------------------------------
# helpers / fixtures
# ---------------------------------------------------------------------------

def _ok(name: str) -> StepResult:
    return StepResult(name, "ok", n_total=1, n_ok=1)


def _failed(name: str) -> StepResult:
    return StepResult(name, "failed", n_total=1, n_failed=1, error="boom")


@pytest.fixture
def patched_steps(monkeypatch):
    """Patch every _steps callable to record calls and return ok by default."""
    calls: list[str] = []

    def mk(name_fmt):
        def fn(target, **kwargs):
            name = name_fmt.format(**kwargs)
            calls.append(name)
            return _ok(name)
        return fn

    monkeypatch.setattr(_steps, "acquire_rinex", mk("acquire_rinex"))
    monkeypatch.setattr(_steps, "acquire_brdc", mk("acquire_brdc"))
    monkeypatch.setattr(_steps, "acquire_l6", mk("acquire_l6"))
    monkeypatch.setattr(_steps, "process", mk("process:{mode}"))
    monkeypatch.setattr(_steps, "qc_teqc", mk("qc_teqc"))
    monkeypatch.setattr(_steps, "qc_summarize", mk("qc_summarize"))
    # default: nothing pre-exists
    monkeypatch.setattr(daily, "is_day_complete", lambda *a, **k: False)
    return calls


MODES = ("verify", "ttff_verify")


# ---------------------------------------------------------------------------
# run_day
# ---------------------------------------------------------------------------

def test_run_day_full_chain_order(patched_steps, tmp_path):
    rec = tmp_path / "orch.jsonl"
    res = daily.run_day(
        date(2026, 4, 1), modes=MODES, record_path=rec
    )
    assert res.status == "ok"
    assert patched_steps == [
        "acquire_rinex",
        "acquire_brdc",
        "acquire_l6",
        "process:verify",
        "process:ttff_verify",
        "qc_teqc",
        "qc_summarize",
    ]
    # one JSONL record written
    lines = rec.read_text().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["kind"] == "daily"
    assert payload["date"] == "2026-04-01"
    assert payload["status"] == "ok"
    assert len(payload["steps"]) == 7


def test_run_day_skip_acquire(patched_steps, tmp_path):
    res = daily.run_day(
        date(2026, 4, 1), modes=MODES, skip_acquire=True, record_path=tmp_path / "r.jsonl"
    )
    assert res.status == "ok"
    assert patched_steps == [
        "process:verify",
        "process:ttff_verify",
        "qc_teqc",
        "qc_summarize",
    ]


def test_run_day_rinex_failure_gates_downstream(patched_steps, monkeypatch, tmp_path):
    monkeypatch.setattr(_steps, "acquire_rinex", lambda target, **k: _failed("acquire_rinex"))
    res = daily.run_day(date(2026, 4, 1), modes=MODES, record_path=tmp_path / "r.jsonl")
    # process / qc never invoked
    assert "process:verify" not in patched_steps
    assert "qc_teqc" not in patched_steps
    names = {s.name: s.status for s in res.steps}
    assert names["acquire_rinex"] == "failed"
    assert names["process:verify"] == "skipped"
    assert names["qc_teqc"] == "skipped"
    assert names["qc_summarize"] == "skipped"
    assert res.status == "partial"  # acquire_brdc/l6 ran ok


def test_run_day_teqc_failure_skips_summarize(patched_steps, monkeypatch, tmp_path):
    monkeypatch.setattr(_steps, "qc_teqc", lambda target, **k: _failed("qc_teqc"))
    res = daily.run_day(date(2026, 4, 1), modes=MODES, record_path=tmp_path / "r.jsonl")
    assert "qc_summarize" not in patched_steps
    names = {s.name: s.status for s in res.steps}
    assert names["qc_summarize"] == "skipped"
    assert res.status == "partial"


def test_run_day_already_complete_short_circuits(patched_steps, monkeypatch, tmp_path):
    monkeypatch.setattr(daily, "is_day_complete", lambda *a, **k: True)
    res = daily.run_day(date(2026, 4, 1), modes=MODES, record_path=tmp_path / "r.jsonl")
    assert patched_steps == []  # nothing ran
    assert res.status == "ok"
    assert len(res.steps) == 1 and res.steps[0].status == "skipped"


def test_run_day_force_bypasses_complete_check(patched_steps, monkeypatch, tmp_path):
    monkeypatch.setattr(daily, "is_day_complete", lambda *a, **k: True)
    daily.run_day(date(2026, 4, 1), modes=MODES, force=True, record_path=tmp_path / "r.jsonl")
    assert "process:verify" in patched_steps  # ran despite "complete"


# ---------------------------------------------------------------------------
# is_day_complete
# ---------------------------------------------------------------------------

def test_is_day_complete(tmp_path, monkeypatch):
    from pntmoni_pipeline.processing import claslib_engine
    from pntmoni_pipeline.qc import _summary

    target = date(2026, 4, 1)
    out_root = tmp_path / "processed"
    qc_root = tmp_path / "qc_summary"

    # nothing present yet
    assert not daily.is_day_complete(
        target, modes=MODES, output_root=out_root, qc_summary_root=qc_root
    )

    # create qc summary parquet
    qc_path = _summary.output_path(qc_root, target)
    qc_path.parent.mkdir(parents=True, exist_ok=True)
    qc_path.write_text("x")
    # still missing pos dirs
    assert not daily.is_day_complete(
        target, modes=MODES, output_root=out_root, qc_summary_root=qc_root
    )

    # create a .pos for each mode
    for mode in MODES:
        d = claslib_engine.output_dir(out_root, mode, target)
        d.mkdir(parents=True, exist_ok=True)
        (d / "00010920.pos").write_text("x")
    assert daily.is_day_complete(
        target, modes=MODES, output_root=out_root, qc_summary_root=qc_root
    )


# ---------------------------------------------------------------------------
# acquire_brdc fetches target day + next day
# ---------------------------------------------------------------------------

def test_acquire_brdc_fetches_target_and_next_day(monkeypatch, tmp_path):
    """Processing needs BRDC of target day AND next day — acquire both."""
    calls: list[date] = []

    class _FakeResult:
        skipped = False

    def fake_fetch(target, dest_root, *, overwrite=False):
        calls.append(target)
        return _FakeResult()

    monkeypatch.setattr(_steps.cddis_brdc, "fetch", fake_fetch)
    res = _steps.acquire_brdc(date(2026, 5, 1), raw_root=tmp_path)
    assert calls == [date(2026, 5, 1), date(2026, 5, 2)]
    assert res.status == "ok"
    assert res.n_total == 2


# ---------------------------------------------------------------------------
# backfill
# ---------------------------------------------------------------------------

def test_date_range_inclusive():
    days = list(backfill.date_range(date(2026, 4, 1), date(2026, 4, 3)))
    assert days == [date(2026, 4, 1), date(2026, 4, 2), date(2026, 4, 3)]


def test_date_range_rejects_reversed():
    with pytest.raises(ValueError):
        list(backfill.date_range(date(2026, 4, 3), date(2026, 4, 1)))


def test_run_range_continues_on_error(monkeypatch):
    seen: list[date] = []

    def fake_run_day(target, **kwargs):
        seen.append(target)
        if target == date(2026, 4, 2):
            raise RuntimeError("hard abort")
        return daily.DayResult(
            target=target, steps=[_ok("process:verify")], status="ok",
            started_at=_now(), finished_at=_now(), wall_sec=0.1,
        )

    monkeypatch.setattr(backfill, "run_day", fake_run_day)
    res = backfill.run_range(date(2026, 4, 1), date(2026, 4, 3), modes=MODES)
    # all three days attempted despite the middle one aborting
    assert seen == [date(2026, 4, 1), date(2026, 4, 2), date(2026, 4, 3)]
    assert res.by_status() == {"ok": 2, "failed": 1}
    assert res.n_failed == 1


def _now():
    from datetime import UTC, datetime
    return datetime.now(UTC)
