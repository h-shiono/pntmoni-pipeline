"""Unit tests for strict-TTFF Stage 2b + monthly roll-up."""
from __future__ import annotations

import textwrap
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pntmoni_pipeline.analysis import (
    _accuracy_stats,
    _coords_math,
    _monthly,
    _registry,
    _ttff_stats,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _registry_sources(tmp_path: Path) -> _registry.RegistrySources:
    na = tmp_path / "na.toml"
    na.write_text(textwrap.dedent("""\
        [stations."0231"]
        netid = 7
        isinside = true
    """))
    ev = tmp_path / "ev.toml"
    ev.write_text(textwrap.dedent("""\
        [stations."0231"]
        periods = [
            { from = 2026-04-01, to = 2026-09-30, fy_label = "fy2026_1st_h" },
        ]
    """))
    ni = tmp_path / "ni.toml"
    ni.write_text("# placeholder\n")
    return _registry.RegistrySources(
        network_assignments=na, network_info=ni, eval_periods=ev,
    )


def _epoch_errors_for_window_pattern(
    station: str,
    *,
    pattern_per_window: list[list[tuple[int, float, float]]],
    sampling_interval_sec: int = 30,
    reset_period_sec: int = 900,
) -> pd.DataFrame:
    """Build a DataFrame with one row per (epoch_idx, station) covering
    several reset windows. ``pattern_per_window[w]`` is a list of
    ``(quality, horizontal_m, vertical_m)`` tuples for the consecutive
    epochs starting at the window boundary; missing trailing entries
    repeat the last one as Q=4 if it exists.
    """
    epochs_per_window = reset_period_sec // sampling_interval_sec
    base = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
    rows = []
    epoch_idx = 0
    for w_pattern in pattern_per_window:
        last = w_pattern[-1] if w_pattern else (4, 0.05, 0.10)
        for k in range(epochs_per_window):
            q, h, v = w_pattern[k] if k < len(w_pattern) else last
            t = base + timedelta(seconds=epoch_idx * sampling_interval_sec)
            rows.append({
                "date": "2026-04-01",
                "station": station,
                "mode": "kinematic_p30_ttff_test",
                "engine_version": "v-test",
                "epoch_idx": epoch_idx,
                "time_utc": t,
                "quality": np.int8(q),
                "num_sat": np.int8(12),
                "e_m": np.float32(h / np.sqrt(2)),
                "n_m": np.float32(h / np.sqrt(2)),
                "u_m": np.float32(v),
                "horizontal_m": np.float32(h),
                "vertical_m": np.float32(v),
                "is_day": True,
            })
            epoch_idx += 1
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# _ttff_per_station: strict criterion
# ---------------------------------------------------------------------------

def test_ttff_per_station_strict_requires_accuracy_threshold() -> None:
    # Window 0: Q=4 from epoch 1 BUT horizontal_m starts at 1.0 (above
    # threshold) and only drops to 0.05 at epoch 5.
    pattern = [[
        (1, 5.0, 5.0),     # epoch 0 — Q=1 → not fix
        (4, 1.0, 0.5),     # epoch 1 — Q=4 but hor 1.0 > 0.12 → not fix
        (4, 0.5, 0.3),     # epoch 2 — Q=4 but hor 0.5 > 0.12 → not fix
        (4, 0.05, 0.20),   # epoch 3 — Q=4, hor 0.05 ≤ 0.12, ver 0.20 ≤ 0.24 → FIX (90s)
        (4, 0.05, 0.10),
    ]]
    df = _epoch_errors_for_window_pattern("0231", pattern_per_window=pattern)
    events = _ttff_stats._ttff_per_station(
        df,
        reset_period_sec=900, sampling_interval_sec=30,
        horizontal_threshold_m=_coords_math.KINEMATIC_H,
        vertical_threshold_m=_coords_math.KINEMATIC_V,
        n_windows=1,
    )
    assert len(events) == 1
    # Strict TTFF picks epoch 3 → 90 s. The simple-Q=4 logic would have
    # picked epoch 1 → 30 s.
    assert events.iloc[0]["ttff_sec"] == 90.0


def test_ttff_per_station_unfixed_when_threshold_never_met() -> None:
    pattern = [[(4, 1.0, 0.5)] * 30]  # Q=4 throughout but hor never ≤ 0.12
    df = _epoch_errors_for_window_pattern("0231", pattern_per_window=pattern)
    events = _ttff_stats._ttff_per_station(
        df,
        reset_period_sec=900, sampling_interval_sec=30,
        horizontal_threshold_m=_coords_math.KINEMATIC_H,
        vertical_threshold_m=_coords_math.KINEMATIC_V,
        n_windows=1,
    )
    assert pd.isna(events.iloc[0]["ttff_sec"])


def test_compute_station_ttff_day_night_split(tmp_path: Path) -> None:
    # 96 windows × 30 epochs = 2880 epochs (full day at 30 s).
    pattern: list[list[tuple[int, float, float]]] = []
    for w in range(96):
        # First 3 epochs are Q=1, next 27 are Q=4 with hor=0.05 (passes).
        win = [(1, 5.0, 5.0)] * 3 + [(4, 0.05, 0.10)] * 27
        pattern.append(win)
    df = _epoch_errors_for_window_pattern("0231", pattern_per_window=pattern)
    summary, events = _ttff_stats.compute_station_ttff(
        df,
        target_date=date(2026, 4, 1),
        mode="kinematic_p30_ttff_test",
        engine_version="v-test",
        reset_period_sec=900,
        sampling_interval_sec=30,
        horizontal_threshold_m=_coords_math.KINEMATIC_H,
        vertical_threshold_m=_coords_math.KINEMATIC_V,
    )
    # Each window converges at epoch 3 → ttff = 90 s.
    assert summary.shape[0] == 3                            # all/day/night rows
    row_all = summary[summary["window"] == "all"].iloc[0]
    assert row_all["n_windows"] == 96
    assert row_all["fix_success_rate"] == pytest.approx(1.0)
    assert row_all["ttff_p95_sec"] == pytest.approx(90.0)
    # is_day should split into ~52 day windows + ~44 night windows
    # (UTC hours 0-9 and 21-23 = 13 h × 4 = 52 windows day;
    # 10-20 = 11 h × 4 = 44 windows night).
    n_day = int(events["is_day"].sum())
    assert 50 <= n_day <= 53
    assert events.shape[0] == 96
    row_day = summary[summary["window"] == "day"].iloc[0]
    row_night = summary[summary["window"] == "night"].iloc[0]
    assert row_day["n_windows"] == n_day
    assert row_night["n_windows"] == 96 - n_day


# ---------------------------------------------------------------------------
# Network cube
# ---------------------------------------------------------------------------

def test_compute_network_ttff_cube_dimensions(tmp_path: Path) -> None:
    src = _registry_sources(tmp_path)
    reg = _registry.load(date(2026, 4, 1), sources=src)
    # One station with all-good convergence.
    pattern = [[(1, 5.0, 5.0)] * 3 + [(4, 0.05, 0.10)] * 27 for _ in range(96)]
    df = _epoch_errors_for_window_pattern("0231", pattern_per_window=pattern)
    summary, events = _ttff_stats.compute_station_ttff(
        df,
        target_date=date(2026, 4, 1),
        mode="kinematic_p30_ttff_test",
        engine_version="v-test",
        reset_period_sec=900,
        sampling_interval_sec=30,
        horizontal_threshold_m=_coords_math.KINEMATIC_H,
        vertical_threshold_m=_coords_math.KINEMATIC_V,
    )
    completion_by_station = {"0231": 1.0}
    network = _ttff_stats.compute_network_ttff(
        events, reg, completion_by_station,
        target_date=date(2026, 4, 1),
        mode="kinematic_p30_ttff_test",
        engine_version="v-test",
        reset_period_sec=900,
    )
    # Cube shape.
    assert len(network) == 13 * 4 * 3 * 3
    cell = network[
        (network["network_id"] == "all")
        & (network["scope"] == "all")
        & (network["station_set"] == "qualified")
        & (network["window"] == "all")
    ].iloc[0]
    assert cell["n_stations"] == 1
    assert cell["fix_success_rate"] == pytest.approx(1.0)
    assert cell["ttff_p95_sec"] == pytest.approx(90.0)


def test_compute_network_ttff_drops_low_completion_stations(tmp_path: Path) -> None:
    src = _registry_sources(tmp_path)
    reg = _registry.load(date(2026, 4, 1), sources=src)
    # Build events for two stations; station 0231 has full data, station
    # 0232 has only 30 % completion (fails the gate).
    events = pd.DataFrame({
        "station": ["0231"] * 96 + ["0232"] * 96,
        "window_idx": list(range(96)) + list(range(96)),
        "ttff_sec": [60.0] * 96 + [30.0] * 96,
        "is_day": [True] * 96 + [True] * 96,
    })
    completion_by_station = {"0231": 1.0, "0232": 0.3}
    # Add 0232 to the registry so the join survives.
    extra_row = reg.iloc[0].copy()
    extra_row["rinex_id"] = "0232"
    extra_row["netid"] = pd.NA
    extra_row["isinside"] = False
    extra_row["is_eval"] = False
    extra_row["qualified"] = False
    extra_row["is_southern"] = False
    reg2 = pd.concat([reg, pd.DataFrame([extra_row])], ignore_index=True)

    network = _ttff_stats.compute_network_ttff(
        events, reg2, completion_by_station,
        target_date=date(2026, 4, 1), mode="m", engine_version="v",
        reset_period_sec=900,
    )
    # 0232 should be excluded everywhere (below the 90% gate).
    cell = network[
        (network["network_id"] == "all")
        & (network["scope"] == "all")
        & (network["station_set"] == "all")
        & (network["window"] == "all")
    ].iloc[0]
    assert cell["n_stations"] == 1   # only 0231 remains


# ---------------------------------------------------------------------------
# Monthly roll-up
# ---------------------------------------------------------------------------

def test_compute_monthly_pools_all_available_days(tmp_path: Path) -> None:
    src = _registry_sources(tmp_path)
    mode = "kinematic_p30_ttff_test"
    epoch_errors_root = tmp_path / "epoch_errors"

    # Write 2 daily Parquets (April 1 and 5).
    for d in (date(2026, 4, 1), date(2026, 4, 5)):
        path = epoch_errors_root / mode / f"{d.year}" / f"{d.strftime('%Y%m%d')}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        pattern = [[(1, 5.0, 5.0)] * 3 + [(4, 0.05, 0.10)] * 27 for _ in range(96)]
        # Stamp the row date so the monthly rollup keeps temporal order.
        df = _epoch_errors_for_window_pattern("0231", pattern_per_window=pattern)
        df["date"] = d.isoformat()
        df.to_parquet(path, index=False)

    res = _monthly.compute_monthly(
        2026, 4, mode=mode,
        epoch_errors_root=epoch_errors_root,
        output_root=tmp_path / "out",
        registry_sources=src,
        record_provenance=False,
    )
    assert res.period == "2026-04"
    assert res.n_dates_pooled == 2
    for path in (
        res.accuracy_station, res.accuracy_network,
        res.ttff_station, res.ttff_network,
    ):
        assert path.is_file(), path
    monthly_acc = pd.read_parquet(res.accuracy_station)
    # period column should be filled with "2026-04".
    assert (monthly_acc["period"] == "2026-04").all()
    # n_epoch in pooled monthly should equal sum of 2 daily epoch counts.
    pooled_total = (
        monthly_acc[(monthly_acc["station"] == "0231") & (monthly_acc["window"] == "all")]
        ["n_epoch"]
        .iloc[0]
    )
    assert pooled_total == 2 * 96 * 30  # 2 days × 96 windows × 30 epochs/window
