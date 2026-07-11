"""Unit tests for the registry loader and accuracy_stats Stage 2a."""
from __future__ import annotations

import textwrap
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pntmoni_pipeline.analysis import _accuracy_stats, _registry


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def _write_minimal_registry(tmp_path: Path) -> _registry.RegistrySources:
    na = tmp_path / "na.toml"
    na.write_text(textwrap.dedent("""\
        [stations."0231"]
        netid = 7
        isinside = true

        [stations."1098"]
        isinside = false

        [stations."0500"]
        netid = 1
        isinside = true
    """))
    ev = tmp_path / "ev.toml"
    ev.write_text(textwrap.dedent("""\
        [stations."0231"]
        periods = [
            { from = 2024-04-01, to = 2024-09-30, fy_label = "fy2024_1st_h" },
            { from = 2024-10-01, to = 2025-03-31, fy_label = "fy2024_2nd_h" },
        ]
        [stations."0500"]
        periods = [
            { from = 2024-01-01, to = 2024-06-30, fy_label = "fy2023_2nd_h" },
            # gap intentionally
            { from = 2025-01-01, to = 2025-03-31, fy_label = "post_recovery" },
        ]
    """))
    ni = tmp_path / "ni.toml"
    ni.write_text("# placeholder\n")
    return _registry.RegistrySources(
        network_assignments=na, network_info=ni, eval_periods=ev,
    )


def test_registry_resolves_is_eval_at_target_date(tmp_path: Path) -> None:
    src = _write_minimal_registry(tmp_path)
    df = _registry.load(date(2024, 5, 15), sources=src)
    assert set(df["rinex_id"]) == {"0231", "0500", "1098"}
    row_0231 = df[df["rinex_id"] == "0231"].iloc[0]
    assert row_0231["is_eval"] is np.True_ or bool(row_0231["is_eval"]) is True
    assert int(row_0231["netid"]) == 7
    assert bool(row_0231["isinside"])
    # 0500 in fy2023_2nd_h period (2024-01-01..06-30) → in eval here.
    assert bool(df[df["rinex_id"] == "0500"].iloc[0]["is_eval"])
    # 1098 has no eval period at all.
    assert not bool(df[df["rinex_id"] == "1098"].iloc[0]["is_eval"])


def test_registry_eval_gap_period(tmp_path: Path) -> None:
    src = _write_minimal_registry(tmp_path)
    df = _registry.load(date(2024, 8, 15), sources=src)
    row_0500 = df[df["rinex_id"] == "0500"].iloc[0]
    # 2024-08-15 is in the gap (after 06-30, before 2025-01-01).
    assert not bool(row_0500["is_eval"])


def test_registry_qualified_collapses_to_is_eval_when_qc_missing(tmp_path: Path) -> None:
    src = _write_minimal_registry(tmp_path)
    df = _registry.load(date(2024, 5, 15), sources=src)
    # qualified == is_eval today (qc_pass is None placeholder).
    assert (df["qualified"] == df["is_eval"]).all()


def test_registry_southern_flag(tmp_path: Path) -> None:
    src = _write_minimal_registry(tmp_path)
    df = _registry.load(date(2024, 5, 15), sources=src)
    # 0500 is netid=1 (southern); 0231 is netid=7 (not southern).
    assert bool(df[df["rinex_id"] == "0500"].iloc[0]["is_southern"])
    assert not bool(df[df["rinex_id"] == "0231"].iloc[0]["is_southern"])


def test_registry_qualification_merge_overrides_eval_and_qualified(tmp_path: Path) -> None:
    """When a qualification parquet is supplied, its is_eval (= force_eval),
    qc_pass, and qualified flags must override the period-derived defaults.
    Use case: Monthly 速報 wants the latest-period CLAS 72 (force_eval) and
    QC-derived qualified set even when target_date is past all eval_periods
    entries (e.g. 2026-04 vs eval_periods ending 2025-09-30).
    """
    src = _write_minimal_registry(tmp_path)
    # 2026-04-30 — past every period in the minimal registry; the
    # period-derived is_eval is False for everyone.
    target = date(2026, 4, 30)
    base = _registry.load(target, sources=src)
    assert not base["is_eval"].any()
    assert not base["qualified"].any()

    qpath = tmp_path / "q.parquet"
    pd.DataFrame([
        # 0231 — qc_pass True, force_eval True (latest-period fallback hit)
        {"station": "0231", "qc_pass": True,  "force_eval": True,
         "out_of_service": False, "qualified": True},
        # 0500 — qc_pass False but force_eval True → still qualified
        {"station": "0500", "qc_pass": False, "force_eval": True,
         "out_of_service": False, "qualified": True},
        # 1098 — vetoed by out_of_service even though qc_pass is True
        {"station": "1098", "qc_pass": True,  "force_eval": False,
         "out_of_service": True,  "qualified": False},
    ]).to_parquet(qpath, index=False)

    merged = _registry.load(target, sources=src, qualification_path=qpath)
    by_id = merged.set_index("rinex_id")

    assert bool(by_id.loc["0231", "is_eval"]) is True
    assert bool(by_id.loc["0231", "qualified"]) is True
    assert bool(by_id.loc["0231", "qc_pass"]) is True

    assert bool(by_id.loc["0500", "is_eval"]) is True
    assert bool(by_id.loc["0500", "qualified"]) is True
    assert bool(by_id.loc["0500", "qc_pass"]) is False

    assert bool(by_id.loc["1098", "is_eval"]) is False
    assert bool(by_id.loc["1098", "qualified"]) is False
    assert bool(by_id.loc["1098", "out_of_service"]) is True


def test_registry_qualification_merge_missing_columns_raises(tmp_path: Path) -> None:
    src = _write_minimal_registry(tmp_path)
    bad = tmp_path / "bad.parquet"
    pd.DataFrame([{"station": "0231", "qc_pass": True}]).to_parquet(bad, index=False)
    with pytest.raises(ValueError, match="missing columns"):
        _registry.load(date(2024, 5, 15), sources=src, qualification_path=bad)


def test_registry_qualification_merge_path_missing_raises(tmp_path: Path) -> None:
    src = _write_minimal_registry(tmp_path)
    with pytest.raises(FileNotFoundError):
        _registry.load(
            date(2024, 5, 15), sources=src,
            qualification_path=tmp_path / "does_not_exist.parquet",
        )


# ---------------------------------------------------------------------------
# Synthetic epoch_errors fixture
# ---------------------------------------------------------------------------

def _make_epoch_errors(stations_to_errors: dict[str, tuple[float, float, int]]) -> pd.DataFrame:
    """Build a synthetic epoch_errors frame.

    ``stations_to_errors[station]`` = (h_error_const, v_error_const, q).
    Each station gets 6 epochs, mix of day/night.
    """
    rows = []
    base = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
    for station, (h_err, v_err, q) in stations_to_errors.items():
        for i in range(6):
            t = base + timedelta(seconds=30 * i)
            is_day = t.hour in set(range(0, 10)) | set(range(21, 24))
            rows.append({
                "date": "2026-04-01",
                "station": station,
                "mode": "kinematic_p30_test",
                "engine_version": "v-test",
                "epoch_idx": i,
                "time_utc": t,
                "quality": np.int8(q),
                "num_sat": np.int8(12),
                "e_m": np.float32(h_err / np.sqrt(2)),
                "n_m": np.float32(h_err / np.sqrt(2)),
                "u_m": np.float32(v_err),
                "horizontal_m": np.float32(h_err),
                "vertical_m": np.float32(v_err),
                "is_day": is_day,
            })
    return pd.DataFrame(rows)


def test_compute_station_accuracy_basic_metrics() -> None:
    # Two stations, all Q=4 with constant errors → percentiles equal the value.
    df = _make_epoch_errors({"0231": (0.05, 0.10, 4), "0500": (0.20, 0.40, 4)})
    out = _accuracy_stats.compute_station_accuracy(
        df, target_date=date(2026, 4, 1),
        mode="kinematic_p30_test", engine_version="v-test",
    )
    assert set(out["window"]) == {"all", "day", "night"}
    row = out[(out["station"] == "0231") & (out["window"] == "all")].iloc[0]
    assert row["n_epoch"] == 6
    assert row["fix_rate"] == pytest.approx(1.0)
    assert row["hor_p95"] == pytest.approx(0.05, abs=1e-4)
    assert row["ver_p99"] == pytest.approx(0.10, abs=1e-4)
    assert row["hor_rms"] == pytest.approx(0.05, abs=1e-4)


def test_compute_station_accuracy_fix_rate_and_percentiles_with_q1() -> None:
    # 0231: 4 epochs Q=4 with hor=0.05, 2 epochs Q=1 with hor=10.0 (mocked via different stations).
    rows = []
    base = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    for i in range(6):
        q = 4 if i < 4 else 1
        h = 0.05 if q == 4 else 10.0
        rows.append({
            "date": "2026-04-01",
            "station": "0231",
            "mode": "m", "engine_version": "v",
            "epoch_idx": i,
            "time_utc": base + timedelta(seconds=30 * i),
            "quality": np.int8(q), "num_sat": np.int8(12),
            "e_m": np.float32(h), "n_m": np.float32(0.0),
            "u_m": np.float32(0.0),
            "horizontal_m": np.float32(h),
            "vertical_m": np.float32(0.0),
            "is_day": True,
        })
    df = pd.DataFrame(rows)
    out = _accuracy_stats.compute_station_accuracy(
        df, target_date=date(2026, 4, 1), mode="m", engine_version="v",
    )
    row = out[(out["station"] == "0231") & (out["window"] == "all")].iloc[0]
    assert row["n_epoch"] == 6
    assert row["fix_rate"] == pytest.approx(4 / 6)
    # Q=1 epochs ARE included in percentile calculation (legacy convention).
    # p95 of [0.05, 0.05, 0.05, 0.05, 10.0, 10.0] in linear-interp = ~9.5.
    assert row["hor_p95"] > 5.0


def test_compute_network_accuracy_cube_dimensions(tmp_path: Path) -> None:
    src = _write_minimal_registry(tmp_path)
    reg = _registry.load(date(2024, 5, 15), sources=src)
    # 3 stations (0231, 0500, 1098). All Q=4, distinct error magnitudes.
    df = _make_epoch_errors({
        "0231": (0.05, 0.10, 4),    # netid 7, inside, eval
        "0500": (0.10, 0.20, 4),    # netid 1, inside, eval (southern)
        "1098": (0.50, 1.00, 4),    # no netid, outside, NOT eval
    })
    out = _accuracy_stats.compute_network_accuracy(
        df, reg,
        target_date=date(2024, 5, 15), mode="m", engine_version="v",
    )
    # Dimensions: 13 networks × 4 scopes × 3 station_sets × 3 windows = 468.
    assert len(out) == 468
    expected_cols = {
        "date", "mode", "engine_version",
        "network_id", "scope", "station_set", "window",
        "n_stations", "n_epoch", "n_sat_mean", "fix_rate",
        "hor_p50", "hor_p95", "hor_p99", "hor_p999",
        "ver_p50", "ver_p95", "ver_p99", "ver_p999",
        "hor_rms", "ver_rms",
    }
    assert expected_cols.issubset(out.columns)


def test_compute_network_accuracy_eval_only_filters_to_eval_stations(tmp_path: Path) -> None:
    src = _write_minimal_registry(tmp_path)
    reg = _registry.load(date(2024, 5, 15), sources=src)
    df = _make_epoch_errors({
        "0231": (0.05, 0.10, 4),    # is_eval=True
        "1098": (10.0, 5.0, 4),     # is_eval=False
    })
    out = _accuracy_stats.compute_network_accuracy(
        df, reg,
        target_date=date(2024, 5, 15), mode="m", engine_version="v",
    )
    # network_id="all", scope="all", station_set="eval_only", window="all".
    cell_eval = out[
        (out["network_id"] == "all")
        & (out["scope"] == "all")
        & (out["station_set"] == "eval_only")
        & (out["window"] == "all")
    ].iloc[0]
    cell_all = out[
        (out["network_id"] == "all")
        & (out["scope"] == "all")
        & (out["station_set"] == "all")
        & (out["window"] == "all")
    ].iloc[0]
    # eval_only excludes 1098; "all" includes both. So eval_only's hor_p95
    # equals 0.05 (only 0231 errors), but "all" gets pulled toward 1098's
    # 10.0.
    assert cell_eval["n_stations"] == 1
    assert cell_eval["hor_p95"] == pytest.approx(0.05, abs=1e-4)
    assert cell_all["n_stations"] == 2
    assert cell_all["hor_p95"] > 1.0


def test_compute_network_accuracy_outside_wo_southern_excludes_southern(tmp_path: Path) -> None:
    src = _write_minimal_registry(tmp_path)
    reg = _registry.load(date(2024, 5, 15), sources=src)
    # All three stations marked "outside" by patching the registry.
    reg.loc[reg["rinex_id"].isin(["0231", "0500", "1098"]), "isinside"] = False
    # 0231 (netid=7), 0500 (netid=1, southern), 1098 (no netid).
    df = _make_epoch_errors({
        "0231": (0.05, 0.10, 4),
        "0500": (0.20, 0.40, 4),
        "1098": (10.0, 5.0, 4),
    })
    out = _accuracy_stats.compute_network_accuracy(
        df, reg,
        target_date=date(2024, 5, 15), mode="m", engine_version="v",
    )
    cell = out[
        (out["network_id"] == "all")
        & (out["scope"] == "outside_wo_southern")
        & (out["station_set"] == "all")
        & (out["window"] == "all")
    ].iloc[0]
    # 0500 (netid=1, southern) is excluded; 0231 (netid=7) and 1098
    # (no netid → is_southern=False) remain.
    assert cell["n_stations"] == 2


# ---------------------------------------------------------------------------
# Receiver × firmware (equipment) accuracy — Pro §6.3
# ---------------------------------------------------------------------------

def _flat_registry(station_flags: dict[str, tuple[bool, bool]]) -> pd.DataFrame:
    """Minimal registry frame: {station: (is_eval, qualified)}."""
    return pd.DataFrame([
        {"rinex_id": s, "is_eval": ev, "qualified": q}
        for s, (ev, q) in station_flags.items()
    ])


def test_compute_equipment_accuracy_groups_by_combo_and_pools() -> None:
    # Two combos of 3 stations each; constant errors → pooled percentile
    # equals the value.
    errs = {
        "S1": (0.05, 0.10, 4), "S2": (0.05, 0.10, 4), "S3": (0.05, 0.10, 4),
        "S4": (0.20, 0.40, 4), "S5": (0.20, 0.40, 4), "S6": (0.20, 0.40, 4),
    }
    df = _make_epoch_errors(errs)
    reg = _flat_registry({s: (True, True) for s in errs})
    equip = pd.DataFrame([
        {"station": s, "rec_type": "TRIMBLE NETR9", "rec_fw_ver": "5.45"}
        for s in ("S1", "S2", "S3")
    ] + [
        {"station": s, "rec_type": "SEPT POLARX5", "rec_fw_ver": "5.3.2"}
        for s in ("S4", "S5", "S6")
    ])
    out = _accuracy_stats.compute_equipment_accuracy(
        df, equip, reg, target_date=date(2026, 4, 1), mode="m", engine_version="v",
    )
    cell_a = out[(out["rec_type"] == "TRIMBLE NETR9")
                 & (out["station_set"] == "all") & (out["window"] == "all")].iloc[0]
    cell_b = out[(out["rec_type"] == "SEPT POLARX5")
                 & (out["station_set"] == "all") & (out["window"] == "all")].iloc[0]
    assert cell_a["n_stations"] == 3
    assert cell_a["hor_p95"] == pytest.approx(0.05, abs=1e-4)
    assert cell_b["n_stations"] == 3
    assert cell_b["hor_p95"] == pytest.approx(0.20, abs=1e-4)
    # Long-format schema carries the combo keys + the shared metric kernel.
    assert {"rec_type", "rec_fw_ver", "station_set", "window",
            "n_stations", "hor_p95", "ver_p95"}.issubset(out.columns)


def test_compute_equipment_accuracy_suppresses_small_combos() -> None:
    # Combo A has 3 stations (survives); combo C has 1 station (dropped,
    # ADR 0013 small-combo suppression at the default threshold of 3).
    errs = {
        "S1": (0.05, 0.10, 4), "S2": (0.05, 0.10, 4), "S3": (0.05, 0.10, 4),
        "S7": (0.9, 0.9, 4),
    }
    df = _make_epoch_errors(errs)
    reg = _flat_registry({s: (True, True) for s in errs})
    equip = pd.DataFrame([
        {"station": s, "rec_type": "TRIMBLE NETR9", "rec_fw_ver": "5.45"}
        for s in ("S1", "S2", "S3")
    ] + [{"station": "S7", "rec_type": "RARE RX", "rec_fw_ver": "0.1"}])
    out = _accuracy_stats.compute_equipment_accuracy(
        df, equip, reg, target_date=date(2026, 4, 1), mode="m", engine_version="v",
    )
    assert "RARE RX" not in set(out["rec_type"])
    assert "TRIMBLE NETR9" in set(out["rec_type"])


def test_compute_equipment_accuracy_station_set_filter() -> None:
    # 3 stations in one combo; only 2 are qualified → the qualified cell
    # drops below the min-3 threshold and is suppressed, while the "all"
    # cell (3 stations) survives.
    errs = {"S1": (0.05, 0.1, 4), "S2": (0.05, 0.1, 4), "S3": (0.05, 0.1, 4)}
    df = _make_epoch_errors(errs)
    reg = _flat_registry({"S1": (True, True), "S2": (True, True), "S3": (True, False)})
    equip = pd.DataFrame([
        {"station": s, "rec_type": "RX", "rec_fw_ver": "1.0"} for s in errs
    ])
    out = _accuracy_stats.compute_equipment_accuracy(
        df, equip, reg, target_date=date(2026, 4, 1), mode="m", engine_version="v",
    )
    all_cell = out[(out["station_set"] == "all") & (out["window"] == "all")]
    qual_cell = out[(out["station_set"] == "qualified") & (out["window"] == "all")]
    assert len(all_cell) == 1 and int(all_cell.iloc[0]["n_stations"]) == 3
    assert qual_cell.empty  # 2 qualified < min 3 → suppressed


def test_compute_equipment_accuracy_empty_equipment_returns_empty() -> None:
    df = _make_epoch_errors({"S1": (0.05, 0.1, 4)})
    reg = _flat_registry({"S1": (True, True)})
    empty = pd.DataFrame(columns=["station", "rec_type", "rec_fw_ver"])
    out = _accuracy_stats.compute_equipment_accuracy(
        df, empty, reg, target_date=date(2026, 4, 1), mode="m", engine_version="v",
    )
    assert out.empty
    assert {"rec_type", "rec_fw_ver", "station_set", "window"}.issubset(out.columns)
