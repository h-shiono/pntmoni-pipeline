"""Unit tests for coords math and Stage 1 epoch_errors."""
from __future__ import annotations

import textwrap
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pntmoni_pipeline.analysis import _coords_math, _epoch_errors


# ---------------------------------------------------------------------------
# Coords math
# ---------------------------------------------------------------------------

def test_dm2deg_basic() -> None:
    # 35°27.92' (dm form 3527.92) → 35.4654
    assert _coords_math.dm2deg(3527.92) == pytest.approx(35.4654, abs=1e-4)
    assert _coords_math.dm2deg(13915.20) == pytest.approx(139.2533, abs=1e-4)


def test_blh_xyz_round_trip() -> None:
    # Tsukuba1 ITRF2014 ≈ ECEF (-3957162.5, 3310203.5, 3737752.3)
    blh = np.array([np.deg2rad(36.10573), np.deg2rad(140.08720), 70.0])
    xyz = _coords_math.blh_rad_to_xyz(*blh)
    assert xyz[0] == pytest.approx(-3.957e6, rel=1e-4)
    blh_back = _coords_math.xyz_to_blh_rad(xyz)
    assert blh_back[0] == pytest.approx(blh[0], abs=1e-9)
    assert blh_back[1] == pytest.approx(blh[1], abs=1e-9)
    assert blh_back[2] == pytest.approx(blh[2], abs=1e-3)


def test_xyz_to_enu_zero_offset() -> None:
    base = np.array([-3.957e6, 3.310e6, 3.737e6])
    enu = _coords_math.xyz_to_enu(base, base)
    np.testing.assert_allclose(enu, [0.0, 0.0, 0.0], atol=1e-9)


def test_xyz_to_enu_known_vertical_offset() -> None:
    # Construct a rover that is 1 m higher than base in geodetic height.
    base_blh = np.array([np.deg2rad(36.0), np.deg2rad(140.0), 50.0])
    base_xyz = _coords_math.blh_rad_to_xyz(*base_blh)
    rover_blh = np.array([np.deg2rad(36.0), np.deg2rad(140.0), 51.0])
    rover_xyz = _coords_math.blh_rad_to_xyz(*rover_blh)
    enu = _coords_math.xyz_to_enu(rover_xyz, base_xyz)
    assert abs(enu[0]) < 1e-3 and abs(enu[1]) < 1e-3
    assert enu[2] == pytest.approx(1.0, abs=1e-3)


def test_xyz_to_enu_vectorised_matches_loop() -> None:
    base_blh = np.array([np.deg2rad(36.0), np.deg2rad(140.0), 50.0])
    base_xyz = _coords_math.blh_rad_to_xyz(*base_blh)
    rovers = []
    for dh in (0.5, 1.5, 2.5):
        rover_blh = np.array([np.deg2rad(36.0), np.deg2rad(140.0), 50.0 + dh])
        rovers.append(_coords_math.blh_rad_to_xyz(*rover_blh))
    rovers_arr = np.vstack(rovers)
    enus_vec = _coords_math.xyz_to_enu(rovers_arr, base_xyz)
    enus_loop = np.vstack([
        _coords_math.xyz_to_enu(r, base_xyz) for r in rovers
    ])
    np.testing.assert_allclose(enus_vec, enus_loop, atol=1e-9)


def test_thresholds_for_mode() -> None:
    th = _coords_math.thresholds_for_mode("kinematic_p30_ttff_verify")
    assert th.horizontal_m == _coords_math.KINEMATIC_H
    assert th.vertical_m == _coords_math.KINEMATIC_V
    th = _coords_math.thresholds_for_mode("static_clas")
    assert th.horizontal_m == _coords_math.STATIC_H
    with pytest.raises(ValueError):
        _coords_math.thresholds_for_mode("unknown_mode_xyz")


# ---------------------------------------------------------------------------
# NMEA parsing
# ---------------------------------------------------------------------------

_NMEA_FIXTURE = textwrap.dedent("""\
    $GPRMC,235942.00,A,3827.9232294,N,13915.2025186,E,0.01,0.00,310326,0.0,E,D*31
    $GPGGA,235942.00,3827.9232294,N,13915.2025186,E,5,13,0.9,9.428,M,38.220,M,0.0,*44
    $GPRMC,000012.00,A,3827.9231659,N,13915.2024364,E,0.07,0.00,010426,0.0,E,D*32
    $GPGGA,000012.00,3827.9231659,N,13915.2024364,E,5,12,1.0,9.610,M,38.220,M,0.0,*45
    $GPRMC,000042.00,A,3827.9233195,N,13915.2024011,E,0.03,0.00,010426,0.0,E,D*39
    $GPGGA,000042.00,3827.9233195,N,13915.2024011,E,4,16,0.7,9.150,M,38.220,M,0.0,*40
""")


def test_parse_pos_nmea_extracts_three_epochs(tmp_path: Path) -> None:
    p = tmp_path / "0231.pos"
    p.write_text(_NMEA_FIXTURE)
    df = _epoch_errors.parse_pos_nmea(p)
    assert len(df) == 3
    # First row: UTC 23:59:42 of 2026-03-31 → GPST 2026-04-01 00:00:00 → epoch 0.
    assert int(df["epoch_idx"].iloc[0]) == 0
    assert int(df["epoch_idx"].iloc[1]) == 1
    assert int(df["epoch_idx"].iloc[2]) == 2
    assert int(df["quality"].iloc[2]) == 4
    assert int(df["num_sat"].iloc[2]) == 16
    # Lat 38°27.92'N → +38.4654° (within parsing precision).
    assert df["lat_deg"].iloc[0] == pytest.approx(38.4654, abs=1e-3)
    # Lon 139°15.20'E → +139.2533°.
    assert df["lon_deg"].iloc[0] == pytest.approx(139.2533, abs=1e-3)


def test_parse_pos_nmea_skips_pre_rmc_gga(tmp_path: Path) -> None:
    # If a $GPGGA appears before any $GPRMC, we have no date → row dropped.
    p = tmp_path / "x.pos"
    p.write_text(
        "$GPGGA,000042.00,3827.92,N,13915.20,E,4,12,1.0,9.0,M,38.2,M,0.0,*40\n"
        + _NMEA_FIXTURE
    )
    df = _epoch_errors.parse_pos_nmea(p)
    # Same 3 rows from the fixture, no extra (pre-RMC GGA was dropped).
    assert len(df) == 3


# ---------------------------------------------------------------------------
# Stage 1 driver: end-to-end on synthetic .pos + ref Parquet
# ---------------------------------------------------------------------------

def _write_synthetic_pos(path: Path, station: str, fixture: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fixture)
    return path


def _write_synthetic_ref_parquet(
    out_path: Path, target: date, stations: dict[str, tuple[float, float, float]],
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "f5_id": rid,
            "rinex_id": rid,
            "j_name": "",
            "e_name": "",
            "target_date": target.isoformat(),
            "x_m": x, "y_m": y, "z_m": z,
            "rel_x_m": 0.0, "rel_y_m": 0.0, "rel_z_m": 0.0,
            "n_days_used": 15, "n_days_in_window": 15,
            "frame": "ITRF2014",
        }
        for rid, (x, y, z) in stations.items()
    ]
    pd.DataFrame(rows).to_parquet(out_path, index=False)
    return out_path


def test_compute_epoch_errors_end_to_end(tmp_path: Path) -> None:
    target = date(2026, 4, 1)
    mode = "kinematic_p30_ttff_verify"

    # 1. Synthetic .pos file for one station, three epochs (header above).
    pos_path = tmp_path / "processed" / mode / "2026" / "091" / "02310910.pos"
    _write_synthetic_pos(pos_path, "0231", _NMEA_FIXTURE)

    # 2. Reference parquet — anchor the station at a coord *near* its NMEA
    #    position so ENU error is small but non-zero.
    rover_lat = 38.4654
    rover_lon = 139.2533
    rover_h = 9.0 + 38.22  # alt + geoid from the fixture's GGA
    rover_xyz = _coords_math.blh_rad_to_xyz(
        np.deg2rad(rover_lat), np.deg2rad(rover_lon), rover_h,
    )
    # Reference is the rover's own approximate position → ENU should be ~0.
    ref_path = tmp_path / "ref.parquet"
    _write_synthetic_ref_parquet(
        ref_path, target,
        {"0231": (float(rover_xyz[0]), float(rover_xyz[1]), float(rover_xyz[2]))},
    )

    res = _epoch_errors.compute_epoch_errors(
        target, mode=mode,
        processed_root=tmp_path / "processed",
        ref_coords_path=ref_path,
        output_root=tmp_path / "epoch_errors",
        engine_version="test-v1",
        record_provenance=False,
    )
    assert res.n_stations == 1
    assert res.n_epochs == 3
    assert res.parquet_path.is_file()

    df = pd.read_parquet(res.parquet_path)
    assert set(df.columns) >= {
        "date", "station", "mode", "engine_version",
        "epoch_idx", "time_utc", "quality", "num_sat",
        "e_m", "n_m", "u_m", "horizontal_m", "vertical_m", "is_day",
    }
    assert (df["station"] == "0231").all()
    assert df["mode"].iloc[0] == mode
    assert df["engine_version"].iloc[0] == "test-v1"
    # The reference-coord we built from rounded lat/lon is only good to
    # ~10s of metres, which is enough to verify the wiring (ENU finite,
    # horizontal small enough that scale is plausibly metres). The exact
    # transform precision is validated separately in the math tests.
    assert df["horizontal_m"].max() < 50.0
    assert df["vertical_m"].max() < 5.0
    # is_day flag: UTC 23:59:42 (= hour 23 ∈ [21,24]) → day.
    #              UTC 00:00:12, 00:00:42 (= hour 0 ∈ [0,9]) → day.
    assert df["is_day"].all()
