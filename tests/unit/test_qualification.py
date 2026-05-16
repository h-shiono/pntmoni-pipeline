"""Tests for the station qualification module."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pntmoni_pipeline.analysis import qualification


# ---------------------------------------------------------------------------
# Threshold derivation
# ---------------------------------------------------------------------------

def _make_qc_table(per_station: dict[str, dict[str, float]]) -> pa.Table:
    """Build a tiny qc_summary parquet-like table.

    ``per_station`` maps station-id → {column_name: value}.
    """
    cols: dict[str, list] = {"id": list(per_station.keys())}
    # Discover all metric columns referenced.
    metric_cols: set[str] = set()
    for vals in per_station.values():
        metric_cols.update(vals.keys())
    for c in sorted(metric_cols):
        cols[c] = [per_station[sid].get(c, float("nan")) for sid in per_station]
    return pa.Table.from_pydict(cols)


def test_derive_thresholds_visibility_lower_direction() -> None:
    # 100 stations, visibility = i/100 (0.00..0.99). 0.27th = index 99*0.9973 = 98 → 0.98 reversed = ?
    # Legacy uses descending sort + idx int(n*0.9973). For descending sorted [0.99, 0.98, ..., 0.0],
    # idx=99 (clamped from int(100*0.9973)=99) → 0.0. That's the worst-case bottom percentile.
    t = pa.Table.from_pydict({
        "id": [f"S{i:03d}" for i in range(100)],
        "visibility": [i / 100.0 for i in range(100)],
    })
    thrs = qualification.derive_thresholds([t])
    vis_thr = next(x for x in thrs if x.metric == "visibility")
    assert vis_thr.direction == "lower"
    # Legacy formula puts the threshold at the 99.73rd index of the
    # descending sort, i.e. value 100 - 99 = 0.00 (very low — the bottom tail).
    assert 0.0 <= vis_thr.value <= 0.01


def test_derive_thresholds_mp_upper_direction() -> None:
    # 1000 stations, MP12@15-20 RMS uniform 0..1.0. 99.73th index = 997 → ~0.997.
    n = 1000
    t = pa.Table.from_pydict({
        "id": [f"S{i:04d}" for i in range(n)],
        "MP12_15_-_20_rms": [i / n for i in range(n)],
    })
    thrs = qualification.derive_thresholds([t])
    mp_thr = next(
        x for x in thrs
        if x.metric == "MP12" and x.bin == "15_-_20"
    )
    assert mp_thr.direction == "upper"
    assert 0.99 <= mp_thr.value <= 1.0


def test_derive_thresholds_sn_lower_direction() -> None:
    # SNR: higher is better, so worst is the LOW tail.
    n = 1000
    t = pa.Table.from_pydict({
        "id": [f"S{i:04d}" for i in range(n)],
        "SN1_15_-_20_mean": [40 + (i / n) * 10 for i in range(n)],  # 40..50 dBHz
    })
    thrs = qualification.derive_thresholds([t])
    sn_thr = next(x for x in thrs if x.metric == "SN1" and x.bin == "15_-_20")
    assert sn_thr.direction == "lower"
    # Legacy descending-sort + 99.73th idx → very low end ≈ 40.0.
    assert 40.0 <= sn_thr.value <= 40.5


def test_derive_thresholds_cs_sums_mp_and_ion() -> None:
    # Two stations, one row each. CS@15-20 = sum(MP*_slps, ION_slps).
    # Pool across two "days": values [(2+3+0+1+0)=6, (1+0+0+0+1)=2]. 99.73th → 6.
    t1 = pa.Table.from_pydict({
        "id": ["A"],
        "MP12_15_-_20_slps": [2.0], "MP21_15_-_20_slps": [3.0],
        "MP15_15_-_20_slps": [0.0], "MP51_15_-_20_slps": [1.0],
        "ION_15_-_20_slps": [0.0],
    })
    t2 = pa.Table.from_pydict({
        "id": ["B"],
        "MP12_15_-_20_slps": [1.0], "MP21_15_-_20_slps": [0.0],
        "MP15_15_-_20_slps": [0.0], "MP51_15_-_20_slps": [0.0],
        "ION_15_-_20_slps": [1.0],
    })
    thrs = qualification.derive_thresholds([t1, t2])
    cs_thr = next(x for x in thrs if x.metric == "CS" and x.bin == "15_-_20")
    assert cs_thr.value == 6.0


# ---------------------------------------------------------------------------
# Force-eval lookup
# ---------------------------------------------------------------------------

def test_load_force_eval_covers_ref_date(tmp_path: Path) -> None:
    toml = tmp_path / "eval.toml"
    toml.write_text(
        '[stations."0007"]\n'
        'periods = [\n'
        '    { from = 2024-10-01, to = 2025-03-31, fy_label = "fy2024_2nd_h", netid = 10 },\n'
        ']\n'
        '[stations."0500"]\n'
        'periods = [\n'
        '    { from = 2025-04-01, to = 2025-09-30, fy_label = "fy2025_1st_h", netid = 1 },\n'
        ']\n',
        encoding="utf-8",
    )
    ids = qualification.load_force_eval_ids(toml, date(2025, 5, 15))
    assert ids == {"0500"}


def test_load_force_eval_falls_back_to_latest_period(tmp_path: Path) -> None:
    """When ref_date is past all known periods, use the latest one."""
    toml = tmp_path / "eval.toml"
    toml.write_text(
        '[stations."0007"]\n'
        'periods = [\n'
        '    { from = 2024-10-01, to = 2025-03-31, fy_label = "fy2024_2nd_h", netid = 10 },\n'
        ']\n'
        '[stations."0500"]\n'
        'periods = [\n'
        '    { from = 2025-04-01, to = 2025-09-30, fy_label = "fy2025_1st_h", netid = 1 },\n'
        ']\n',
        encoding="utf-8",
    )
    # ref_date 2026-04-30 is past all periods. Fallback = latest (fy2025_1st_h)
    # which contains station 0500.
    ids = qualification.load_force_eval_ids(toml, date(2026, 4, 30))
    assert ids == {"0500"}


def test_load_out_of_service(tmp_path: Path) -> None:
    toml = tmp_path / "oos.toml"
    toml.write_text(
        '[stations."1098"]\nreason = "test"\nsince = 2026-04-01\n'
        '[stations."1140"]\nreason = "test"\nsince = 2026-04-01\n',
        encoding="utf-8",
    )
    ids = qualification.load_out_of_service_ids(toml)
    assert ids == {"1098", "1140"}


def test_load_out_of_service_missing_file_is_empty(tmp_path: Path) -> None:
    ids = qualification.load_out_of_service_ids(tmp_path / "nonexistent.toml")
    assert ids == set()


# ---------------------------------------------------------------------------
# End-to-end qualify()
# ---------------------------------------------------------------------------

def _write_qc_summary(path: Path, per_station: dict[str, dict[str, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(_make_qc_table(per_station), path)


def _baseline_station(visibility: float = 0.99) -> dict[str, float]:
    """A station whose values are at the median of the synthetic pool —
    will never trigger an NG flag."""
    row = {"visibility": visibility}
    for b in qualification.ELEV_BINS:
        for mp in qualification.MP_COMBINATIONS:
            row[f"{mp}_{b}_rms"] = 0.30
        for sn in qualification.SN_SIGNALS:
            row[f"{sn}_{b}_mean"] = 48.0
        for part in qualification.CS_PARTS:
            row[f"{part}_{b}_slps"] = 1.0
    return row


def _spike(row: dict[str, float], col: str, value: float) -> dict[str, float]:
    row = dict(row)
    row[col] = value
    return row


def test_qualify_end_to_end_mixed_outcomes(tmp_path: Path) -> None:
    """End-to-end coverage of NG counting + force_eval + out_of_service.

    Each bad station spikes a DIFFERENT metric so its spike count stays
    below the 0.27% percentile cutoff, which keeps the derived threshold
    at the baseline value (not pulled up by the spike). With 200 baseline
    stations × 10 days = 2000 baseline samples, a per-metric spike count
    of ≤ 3 stays under 0.27% of (2000 + 4) ≈ 5.4 → threshold reflects
    baseline cleanly.
    """
    qc_root = tmp_path / "qc_summary"
    eval_toml = tmp_path / "eval.toml"
    oos_toml = tmp_path / "oos.toml"
    net_toml = tmp_path / "net.toml"

    ref_date = date(2026, 4, 30)
    for k in range(10):
        d = ref_date - __import__("datetime").timedelta(days=9 - k)
        per_station: dict[str, dict[str, float]] = {}
        for i in range(200):
            per_station[f"S{i:03d}"] = _baseline_station()
        # B001: MP12 spike day 0 only → 1 NG day
        per_station["B001"] = (
            _spike(_baseline_station(), "MP12_45_-_50_rms", 99.0)
            if k == 0 else _baseline_station()
        )
        # B002: SN1 spike days 0,1,2 → 3 NG days
        per_station["B002"] = (
            _spike(_baseline_station(), "SN1_45_-_50_mean", 5.0)
            if k in (0, 1, 2) else _baseline_station()
        )
        # F001: SN5 spike days 0,1,2 → 3 NG days, but force-eval rescues
        per_station["F001"] = (
            _spike(_baseline_station(), "SN5_45_-_50_mean", 5.0)
            if k in (0, 1, 2) else _baseline_station()
        )
        # X001: out_of_service hard-veto; baseline so we test the veto path
        # independently from NG counting.
        per_station["X001"] = _baseline_station()
        _write_qc_summary(
            qc_root / f"{d.year}" / f"{d.year:04d}{d.month:02d}{d.day:02d}.parquet",
            per_station,
        )

    eval_toml.write_text(
        '[stations."F001"]\n'
        'periods = [{ from = 2026-01-01, to = 2026-12-31, fy_label = "fy2026_test", netid = 7 }]\n'
        '[stations."X001"]\n'
        'periods = [{ from = 2026-01-01, to = 2026-12-31, fy_label = "fy2026_test", netid = 12 }]\n',
        encoding="utf-8",
    )
    oos_toml.write_text(
        '[stations."X001"]\nreason = "test"\nsince = 2026-04-01\n',
        encoding="utf-8",
    )
    net_toml.write_text("", encoding="utf-8")

    result = qualification.qualify(
        ref_date,
        window_days=10,
        ng_days_max=2,
        qc_summary_root=qc_root,
        eval_periods_path=eval_toml,
        out_of_service_path=oos_toml,
        network_assignments_path=net_toml,
    )

    by_id = {r["station"]: r for r in result.rows}

    # Baseline stations all qualified
    for i in range(200):
        sid = f"S{i:03d}"
        assert by_id[sid]["qualified"] is True
        assert by_id[sid]["qc_pass"] is True
        assert by_id[sid]["n_ng_days"] == 0

    # 1 NG day with ng_days_max=2 → qc_pass
    assert by_id["B001"]["n_ng_days"] == 1
    assert by_id["B001"]["qc_pass"] is True
    assert by_id["B001"]["force_eval"] is False
    assert by_id["B001"]["qualified"] is True

    # 3 NG days with ng_days_max=2 → qc_fail, not in force_eval → not qualified
    assert by_id["B002"]["n_ng_days"] == 3
    assert by_id["B002"]["qc_pass"] is False
    assert by_id["B002"]["force_eval"] is False
    assert by_id["B002"]["qualified"] is False

    # Force-eval rescue: qc_fail but force_eval=True → qualified=True
    assert by_id["F001"]["n_ng_days"] == 3
    assert by_id["F001"]["qc_pass"] is False
    assert by_id["F001"]["force_eval"] is True
    assert by_id["F001"]["qualified"] is True

    # Out-of-service veto wins over force_eval (X001 is in both sets;
    # has zero NG-days but is still excluded).
    assert by_id["X001"]["n_ng_days"] == 0
    assert by_id["X001"]["qc_pass"] is True
    assert by_id["X001"]["force_eval"] is True
    assert by_id["X001"]["out_of_service"] is True
    assert by_id["X001"]["qualified"] is False


def test_qualify_default_ng_days_max_uses_legacy_ratio(tmp_path: Path) -> None:
    qc_root = tmp_path / "qc_summary"
    ref_date = date(2026, 4, 30)
    for k in range(89):
        d = ref_date - __import__("datetime").timedelta(days=88 - k)
        per_station = {f"S{i:03d}": _baseline_station() for i in range(20)}
        _write_qc_summary(
            qc_root / f"{d.year}" / f"{d.year:04d}{d.month:02d}{d.day:02d}.parquet",
            per_station,
        )
    eval_toml = tmp_path / "eval.toml"
    eval_toml.write_text("", encoding="utf-8")

    result = qualification.qualify(
        ref_date,
        window_days=89,
        qc_summary_root=qc_root,
        eval_periods_path=eval_toml,
        out_of_service_path=tmp_path / "missing.toml",
        network_assignments_path=tmp_path / "missing.toml",
    )
    assert result.ng_days_max == round(89 * qualification.DEFAULT_NG_RATIO)


def test_write_parquet_and_provenance(tmp_path: Path) -> None:
    qc_root = tmp_path / "qc_summary"
    ref_date = date(2026, 4, 30)
    d = ref_date
    per_station = {f"S{i:03d}": _baseline_station() for i in range(5)}
    _write_qc_summary(
        qc_root / f"{d.year}" / f"{d.year:04d}{d.month:02d}{d.day:02d}.parquet",
        per_station,
    )

    eval_toml = tmp_path / "eval.toml"
    eval_toml.write_text("", encoding="utf-8")

    result = qualification.qualify(
        ref_date,
        window_days=1,
        qc_summary_root=qc_root,
        eval_periods_path=eval_toml,
        out_of_service_path=tmp_path / "missing.toml",
        network_assignments_path=tmp_path / "missing.toml",
    )

    dest = tmp_path / "out.parquet"
    qualification.write_parquet(result, dest)
    table = pq.read_table(dest)
    assert table.num_rows == 5
    md = table.schema.metadata
    assert b"methodology_version" in md
    assert b"window_days" in md

    log = tmp_path / "qual.jsonl"
    qualification.write_provenance_jsonl(result, log)
    record = json.loads(log.read_text(encoding="utf-8").strip())
    assert record["ref_date"] == "2026-04-30"
    assert record["window_days"] == 1
    assert "thresholds" in record and isinstance(record["thresholds"], list)


def test_qualify_raises_when_no_qc_data(tmp_path: Path) -> None:
    eval_toml = tmp_path / "eval.toml"
    eval_toml.write_text("", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        qualification.qualify(
            date(2026, 4, 30),
            window_days=5,
            qc_summary_root=tmp_path / "nothing",
            eval_periods_path=eval_toml,
            out_of_service_path=tmp_path / "missing.toml",
            network_assignments_path=tmp_path / "missing.toml",
        )
