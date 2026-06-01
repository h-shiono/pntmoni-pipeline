"""Tests for the hex-grid spatial aggregation module."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pntmoni_pipeline.analysis import _hex_grid as H


# --- ECEF conversion -------------------------------------------------

def test_ecef_to_geodetic_round_trips_known_points():
    # Tsukuba (92110) approx: 36.10°N, 140.09°E, h≈86m
    lat, lon, h = math.radians(36.10), math.radians(140.09), 86.0
    a = H._WGS84_A
    e2 = H._WGS84_E2
    N = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    x = (N + h) * math.cos(lat) * math.cos(lon)
    y = (N + h) * math.cos(lat) * math.sin(lon)
    z = (N * (1 - e2) + h) * math.sin(lat)

    lon_d, lat_d = H.ecef_to_geodetic(np.array([x]), np.array([y]), np.array([z]))
    assert lon_d[0] == pytest.approx(140.09, abs=1e-5)
    assert lat_d[0] == pytest.approx(36.10, abs=1e-5)


# --- Grid construction -----------------------------------------------

def test_make_hex_grid_default_covers_japan_at_60km():
    g = H.make_hex_grid()
    assert g.spacing_km == 60.0
    assert g.bbox == H.JAPAN_BBOX
    # Sanity: order-of-magnitude. Main GEONET bbox is ~23° lon × 22° lat.
    # At lat~35 that's ~2100 km × 2440 km = ~5.1 M km². Hex area ~2700 km²
    # → expect ~1500-2200 total hexes in bbox (most land cells will hold
    # stations; ocean cells render blank).
    assert 1000 < g.n_hex < 2500
    # Centers lie within the bbox.
    lon_min, lon_max, lat_min, lat_max = g.bbox
    assert (g.centers[:, 0] >= lon_min).all()
    assert (g.centers[:, 0] <= lon_max + 1).all()
    assert (g.centers[:, 1] >= lat_min).all()
    assert (g.centers[:, 1] <= lat_max + 1).all()


def test_hex_vertices_shape_and_distance_to_center():
    g = H.make_hex_grid(spacing_km=60.0)
    # pick a hex near the bbox mid-latitude (cleanest km/deg approximation)
    mid_lat = (g.bbox[2] + g.bbox[3]) / 2.0
    idx = int(np.argmin(np.abs(g.centers[:, 1] - mid_lat)))
    verts = g.vertices(idx)
    assert verts.shape == (6, 2)
    # vertex radius = spacing / sqrt(3) — distance from center should match
    cx, cy = g.centers[idx]
    km_lat, km_lon = g.km_per_deg
    distances_km = np.sqrt(
        ((verts[:, 0] - cx) * km_lon) ** 2
        + ((verts[:, 1] - cy) * km_lat) ** 2,
    )
    expected = 60.0 / math.sqrt(3.0)
    np.testing.assert_allclose(distances_km, expected, rtol=1e-9)


def test_hex_grid_horizontal_spacing_matches_flat_to_flat():
    g = H.make_hex_grid(spacing_km=60.0)
    # Find two horizontally-adjacent centers (same lat, distance ~spacing_km
    # at the bbox mid-latitude).
    lats = np.unique(g.centers[:, 1])
    # Use a row near the bbox mid-latitude so km/deg approximation is exact.
    target_lat = lats[len(lats) // 2]
    row = g.centers[np.isclose(g.centers[:, 1], target_lat)]
    row = row[np.argsort(row[:, 0])]
    assert len(row) >= 2
    km_lon = g.km_per_deg[1]
    diff_km = (row[1, 0] - row[0, 0]) * km_lon
    assert diff_km == pytest.approx(60.0, rel=1e-9)


# --- Station assignment ----------------------------------------------

def test_assign_stations_picks_nearest_center():
    g = H.make_hex_grid(spacing_km=60.0)
    # Build a fake station list whose coords ARE the first 5 hex centers —
    # each should be assigned to itself.
    n = 5
    stations = pd.DataFrame({
        "station": [f"s{i:02d}" for i in range(n)],
        "lon": g.centers[:n, 0],
        "lat": g.centers[:n, 1],
    })
    s2h = H.assign_stations(stations, g)
    assert list(s2h.values) == list(range(n))


def test_assign_stations_uses_station_id_as_index():
    g = H.make_hex_grid(spacing_km=60.0)
    stations = pd.DataFrame({
        "station": ["A", "B"],
        "lon": [g.centers[0, 0], g.centers[1, 0]],
        "lat": [g.centers[0, 1], g.centers[1, 1]],
    })
    s2h = H.assign_stations(stations, g)
    assert s2h["A"] == 0 and s2h["B"] == 1


# --- Aggregation -----------------------------------------------------

def _write_epoch_errors_day(
    root: Path, period: str, day: int, rows: pd.DataFrame,
) -> Path:
    yyyy = int(period[:4])
    mm = int(period[5:7])
    p = root / f"{yyyy}" / f"{yyyy}{mm:02d}{day:02d}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    rows.to_parquet(p, index=False)
    return p


def test_aggregate_epoch_errors_pools_then_quantiles(tmp_path: Path):
    period = "2026-04"
    root = tmp_path / "epoch_errors"
    # Two stations in hex 0 (h: 0.01..0.20), one station in hex 1
    # (h: 0.05..0.10). Vert constant.
    day1 = pd.DataFrame({
        "station": ["s0"] * 10 + ["s1"] * 10 + ["s2"] * 10,
        "horizontal_m": (
            list(np.linspace(0.01, 0.10, 10))
            + list(np.linspace(0.11, 0.20, 10))
            + list(np.linspace(0.05, 0.10, 10))
        ),
        "vertical_m": [0.05] * 30,
    })
    _write_epoch_errors_day(root, period, 1, day1)
    # Empty days should be silently skipped.
    s2h = pd.Series({"s0": 0, "s1": 0, "s2": 1}, name="hex_idx")
    out = H.aggregate_epoch_errors_to_hex(root, period, s2h)
    out = out.sort_values("hex_idx").reset_index(drop=True)
    assert list(out["hex_idx"]) == [0, 1]
    assert list(out["n_stations"]) == [2, 1]
    assert list(out["n_epochs"]) == [20, 10]
    # hex 0 has 20 evenly-spaced points 0.01..0.20 → 95% ≈ 0.19
    assert out.loc[0, "horizontal_p95"] == pytest.approx(0.19, abs=0.005)
    # hex 1 has 10 points 0.05..0.10 → 95%≈ 0.0975
    assert out.loc[1, "horizontal_p95"] == pytest.approx(0.0975, abs=0.005)


def test_aggregate_epoch_errors_supports_multiple_percentiles(tmp_path: Path):
    period = "2026-04"
    root = tmp_path / "epoch_errors"
    rows = pd.DataFrame({
        "station": ["s0"] * 100,
        "horizontal_m": np.linspace(0.0, 1.0, 100),
        "vertical_m": np.linspace(0.0, 0.5, 100),
    })
    _write_epoch_errors_day(root, period, 1, rows)
    s2h = pd.Series({"s0": 0}, name="hex_idx")
    out = H.aggregate_epoch_errors_to_hex(
        root, period, s2h, percentiles=(50.0, 95.0),
    )
    assert {"horizontal_p50", "horizontal_p95",
            "vertical_p50", "vertical_p95"} <= set(out.columns)
    assert out.loc[0, "horizontal_p50"] == pytest.approx(0.5, abs=0.01)
    assert out.loc[0, "vertical_p95"] == pytest.approx(0.475, abs=0.01)


def test_aggregate_handles_missing_days_gracefully(tmp_path: Path):
    period = "2026-04"
    root = tmp_path / "epoch_errors"
    # Only write day 15; the rest should be silently skipped.
    rows = pd.DataFrame({
        "station": ["s0"] * 5,
        "horizontal_m": [0.05, 0.06, 0.07, 0.08, 0.09],
        "vertical_m": [0.05] * 5,
    })
    _write_epoch_errors_day(root, period, 15, rows)
    s2h = pd.Series({"s0": 0}, name="hex_idx")
    out = H.aggregate_epoch_errors_to_hex(root, period, s2h)
    assert len(out) == 1
    assert out.loc[0, "n_epochs"] == 5


def test_aggregate_skips_stations_with_no_hex_assignment(tmp_path: Path):
    period = "2026-04"
    root = tmp_path / "epoch_errors"
    rows = pd.DataFrame({
        "station": ["s0", "s_unknown"] * 5,
        "horizontal_m": [0.05] * 10,
        "vertical_m": [0.05] * 10,
    })
    _write_epoch_errors_day(root, period, 1, rows)
    s2h = pd.Series({"s0": 0}, name="hex_idx")     # s_unknown not mapped
    out = H.aggregate_epoch_errors_to_hex(root, period, s2h)
    assert len(out) == 1
    assert out.loc[0, "n_epochs"] == 5
