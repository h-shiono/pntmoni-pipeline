"""Unit tests for F5 reading and reference-coordinate computation."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pntmoni_pipeline.analysis import _f5_reader, _reference_coords


# ---------------------------------------------------------------------------
# Synthetic F5 fixture builder
# ---------------------------------------------------------------------------

def _write_synthetic_f5(
    root: Path,
    f5_id: str,
    rinex_id: str,
    j_name: str,
    e_name: str,
    year: int,
    daily_xyz: list[tuple[date, float, float, float]],
) -> Path:
    """Write a minimal F5 .pos in the format expected by ``read_f5``."""
    yy = f"{year % 100:02d}"
    out = root / f"{year}" / f"{f5_id}.{yy}.pos"
    out.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "+SITE/INF\n"
        f" ID           {f5_id}\n"
        f" RINEX        {rinex_id}\n"
        f" J_NAME       {j_name}\n"
        f" E_NAME       {e_name}\n"
        "-SITE/INF\n"
        "\n"
        "+SOLVER/INF\n"
        " SOFT_NAME    Bernese\n"
        " EPHEMERIS    IGS\n"
        " SOLUTION_ID  F5(GPS)\n"
        " VERSION      00\n"
        " EPOCH        START=... END=... COUNT=...\n"
        " COORDINATE   ITRF2014\n"
        " ELLIPSOID    GRS80\n"
        "-SOLVER/INF\n"
        "\n"
        "+DATA\n"
        "*yyyy mm dd HH:MM:SS       X (m)             Y (m)             Z (m)         "
        "Lat. (deg.)       Lon. (deg.)       Height (m)\n"
        "*----+--+--+--------+-----------------+-----------------+-----------------+"
        "-----------------+-----------------+-----------------+\n"
    )
    body_lines = []
    for d, x, y, z in daily_xyz:
        # Lat/Lon/H are not used by reference_coords; placeholder zeros.
        body_lines.append(
            f" {d.year:04d} {d.month:02d} {d.day:02d} 12:00:00 "
            f"{x: .10E}  {y: .10E}  {z: .10E}  "
            f"{0.0: .10E}  {0.0: .10E}  {0.0: .10E} "
        )
    footer = (
        "\n"
        "*----+--+--+--------+-----------------+-----------------+-----------------+"
        "-----------------+-----------------+-----------------+\n"
        "-DATA\n"
    )
    out.write_text(header + "\n".join(body_lines) + footer)
    return out


# ---------------------------------------------------------------------------
# F5 reader
# ---------------------------------------------------------------------------

def test_read_f5_metadata_and_rows(tmp_path: Path) -> None:
    days = [(date(2026, 3, d), -3.9e6 + d, 3.5e6, 3.6e6) for d in range(1, 11)]
    p = _write_synthetic_f5(tmp_path, "021098", "1098", "南鳥島", "MINAMI", 2026, days)
    s = _f5_reader.read_f5(p)
    assert s.metadata.f5_id == "021098"
    assert s.metadata.rinex_id == "1098"
    assert s.metadata.j_name == "南鳥島"
    assert s.metadata.frame == "ITRF2014"
    assert s.metadata.ellipsoid == "GRS80"
    assert s.df.shape == (10, 7)
    assert list(s.df.columns) == ["date", "x_m", "y_m", "z_m", "lat_deg", "lon_deg", "h_m"]
    assert s.df["x_m"].iloc[0] == pytest.approx(-3.9e6 + 1)
    assert s.df["x_m"].iloc[-1] == pytest.approx(-3.9e6 + 10)


def _write_synthetic_f5_1(
    root: Path,
    f5_id: str,
    rinex_id: str,
    j_name: str,
    e_name: str,
    year: int,
    daily_xyz: list[tuple[date, float, float, float]],
) -> Path:
    """Write a minimal F5.1 .pos: HISTORY_ID line + ITRF2020 frame.

    F5.1 differs from F5 by an extra ``HISTORY_ID`` line in SOLVER/INF,
    a ``VERSION`` of ``01`` instead of ``00``, and the ITRF2020 frame.
    """
    yy = f"{year % 100:02d}"
    out = root / f"{year}" / f"{f5_id}.{yy}.pos"
    out.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "+SITE/INF\n"
        f" ID           {f5_id}\n"
        f" RINEX        {rinex_id}\n"
        f" J_NAME       {j_name}\n"
        f" E_NAME       {e_name}\n"
        "-SITE/INF\n"
        "\n"
        "+SOLVER/INF\n"
        " SOFT_NAME    Bernese\n"
        " EPHEMERIS    IGS\n"
        " SOLUTION_ID  F5(GPS)\n"
        " VERSION      01\n"
        " EPOCH        START=... END=... COUNT=...\n"
        " COORDINATE   ITRF2020\n"
        " ELLIPSOID    GRS80\n"
        f" HISTORY_ID   {year}-03\n"
        "-SOLVER/INF\n"
        "\n"
        "+DATA\n"
        "*yyyy mm dd HH:MM:SS       X (m)             Y (m)             Z (m)         "
        "Lat. (deg.)       Lon. (deg.)       Height (m)\n"
        "*----+--+--+--------+-----------------+-----------------+-----------------+"
        "-----------------+-----------------+-----------------+\n"
    )
    body = []
    for d, x, y, z in daily_xyz:
        body.append(
            f" {d.year:04d} {d.month:02d} {d.day:02d} 12:00:00 "
            f"{x: .10E}  {y: .10E}  {z: .10E}  "
            f"{0.0: .10E}  {0.0: .10E}  {0.0: .10E} "
        )
    footer = (
        "\n"
        "*----+--+--+--------+-----------------+-----------------+-----------------+"
        "-----------------+-----------------+-----------------+\n"
        "-DATA\n"
    )
    out.write_text(header + "\n".join(body) + footer)
    return out


def test_read_f5_handles_f5_1_variant(tmp_path: Path) -> None:
    """F5.1 has an extra HISTORY_ID line in SOLVER/INF; the reader must
    detect the +DATA marker dynamically rather than rely on a fixed
    header-skip count.
    """
    days = [(date(2026, 4, d), -3.9571625e6 + d * 1e-3, 3.31e6, 3.74e6) for d in range(1, 6)]
    p = _write_synthetic_f5_1(tmp_path, "92110", "2110", "つくば１", "TSUKUBA1", 2026, days)
    s = _f5_reader.read_f5(p)
    assert s.metadata.frame == "ITRF2020"
    assert s.df.shape == (5, 7)
    # First daily row matches the synthetic input.
    assert s.df["x_m"].iloc[0] == pytest.approx(-3.9571625e6 + 1e-3, rel=1e-9)
    assert s.df["date"].iloc[0].day == 1


def test_geonet_f5_variant_routing(tmp_path: Path) -> None:
    from pntmoni_pipeline.acquisition import geonet_f5
    # Routing only — no FTP call. We just assert path strings.
    assert geonet_f5.remote_dir(2026, "f5") == "/data/coordinates_F5/GPS/2026"
    assert geonet_f5.remote_dir(2026, "f5_1") == "/data/coordinates_F5.1/2026"
    v_f5 = geonet_f5.variant_for("f5")
    v_f51 = geonet_f5.variant_for("f5_1")
    assert v_f5.local_subdir == "f5"
    assert v_f51.local_subdir == "f5_1"
    assert v_f5.frame == "ITRF2014"
    assert v_f51.frame == "ITRF2020"
    with pytest.raises(ValueError):
        geonet_f5.variant_for("nope")


# ---------------------------------------------------------------------------
# Common-Mode Removal core
# ---------------------------------------------------------------------------

def test_compute_for_target_recovers_truth(tmp_path: Path) -> None:
    """A 15-day window with stationary truth + per-day common drift should
    recover the truth exactly via per-day relative + median.
    """
    target = date(2026, 3, 15)
    f5_root = tmp_path / "f5"

    # Daily "drift" (common-mode error injected into both stations).
    drift = [(date(2026, 3, target.day + d), float(d) * 0.001) for d in range(-7, 8)]

    # True coords:
    true_fixed = (-3957162.5, 3310203.0, 3737702.0)
    true_other = (-3904422.0, 3484842.0, 3633777.0)

    fixed_days = [
        (d, true_fixed[0] + drift_v, true_fixed[1] + drift_v, true_fixed[2] + drift_v)
        for (d, drift_v) in drift
    ]
    other_days = [
        (d, true_other[0] + drift_v, true_other[1] + drift_v, true_other[2] + drift_v)
        for (d, drift_v) in drift
    ]
    _write_synthetic_f5(f5_root, "92110", "2110", "つくば１", "TSUKUBA1", 2026, fixed_days)
    _write_synthetic_f5(f5_root, "021098", "1098", "南鳥島", "MINAMI", 2026, other_days)

    res = _reference_coords.compute_for_target(
        target, f5_root=f5_root, fixed_station_id="92110",
    )
    df = res.df
    assert set(df["f5_id"]) == {"92110", "021098"}

    # Fixed station: median over identical-drift series ≈ median(true_fixed + drift).
    # With symmetric drift around target, median of drift = drift at target = 0.
    fixed_row = df[df["f5_id"] == "92110"].iloc[0]
    assert fixed_row["x_m"] == pytest.approx(true_fixed[0], abs=1e-6)

    # Other station: per-day relative cancels drift exactly, so the
    # recovered truth must equal the synthetic truth to numerical noise.
    other_row = df[df["f5_id"] == "021098"].iloc[0]
    assert other_row["x_m"] == pytest.approx(true_other[0], abs=1e-6)
    assert other_row["y_m"] == pytest.approx(true_other[1], abs=1e-6)
    assert other_row["z_m"] == pytest.approx(true_other[2], abs=1e-6)


def test_compute_jump_filter_only_applies_to_fixed(tmp_path: Path) -> None:
    """A simulated 'jump' day inflates the fixed station's absolute by a
    large amount AND inflates the other station by the same amount. The
    fixed-station truth should drop the jump day; the other station's
    relative should be invariant and yield the correct truth.
    """
    target = date(2026, 3, 15)
    f5_root = tmp_path / "f5"
    jump_day = date(2026, 3, 12)

    true_fixed = (-3957162.5, 3310203.0, 3737702.0)
    true_other = (-3904422.0, 3484842.0, 3633777.0)
    JUMP = 0.5  # half a metre on every axis on the jump day

    fixed_days = []
    other_days = []
    for d_offset in range(-7, 8):
        d = date(2026, 3, target.day + d_offset)
        delta = JUMP if d == jump_day else 0.0
        fixed_days.append((d, true_fixed[0] + delta, true_fixed[1] + delta, true_fixed[2] + delta))
        other_days.append((d, true_other[0] + delta, true_other[1] + delta, true_other[2] + delta))

    _write_synthetic_f5(f5_root, "92110", "2110", "つくば１", "TSUKUBA1", 2026, fixed_days)
    _write_synthetic_f5(f5_root, "021098", "1098", "南鳥島", "MINAMI", 2026, other_days)

    jumps = [_reference_coords.FixedStationJump(
        date=jump_day, fixed_station_id="92110", reason="synthetic test",
    )]

    res = _reference_coords.compute_for_target(
        target, f5_root=f5_root, fixed_station_id="92110", jumps=jumps,
    )
    df = res.df
    fixed_row = df[df["f5_id"] == "92110"].iloc[0]
    other_row = df[df["f5_id"] == "021098"].iloc[0]

    # Fixed station: median over 14 of 15 days (jump excluded) returns truth.
    assert fixed_row["x_m"] == pytest.approx(true_fixed[0], abs=1e-6)
    # Other station: per-day relative cancels the jump-day common offset exactly.
    assert other_row["x_m"] == pytest.approx(true_other[0], abs=1e-6)
    assert res.applied_jump_dates == [jump_day]
    assert res.n_fixed_days_dropped == 1
    assert res.n_fixed_days_used == 14


def test_compute_raises_if_too_few_fixed_days(tmp_path: Path) -> None:
    target = date(2026, 3, 15)
    f5_root = tmp_path / "f5"
    # Only 5 days of fixed data — under min_fixed_days=7.
    fixed_days = [
        (date(2026, 3, target.day + d), -3957162.5, 3310203.0, 3737702.0)
        for d in range(-2, 3)
    ]
    _write_synthetic_f5(f5_root, "92110", "2110", "つくば１", "TSUKUBA1", 2026, fixed_days)

    with pytest.raises(RuntimeError, match="fixed-station days available"):
        _reference_coords.compute_for_target(
            target, f5_root=f5_root, fixed_station_id="92110",
        )


def test_load_jumps_from_toml(tmp_path: Path) -> None:
    p = tmp_path / "jumps.toml"
    p.write_text(
        '[meta]\nlast_reviewed = "2026-05-09"\n'
        "[[jumps]]\n"
        'date = "2024-01-01"\n'
        'fixed_station_id = "92110"\n'
        'reason = "test"\n'
        'recorded_at = "2026-05-01"\n'
    )
    js = _reference_coords.load_jumps(p)
    assert len(js) == 1
    assert js[0].date == date(2024, 1, 1)
    assert js[0].fixed_station_id == "92110"
    assert js[0].reason == "test"


def test_load_jumps_empty_when_file_missing(tmp_path: Path) -> None:
    js = _reference_coords.load_jumps(tmp_path / "does_not_exist.toml")
    assert js == []


def test_compute_for_targets_multi_day(tmp_path: Path) -> None:
    """Driving compute_for_targets across 3 days yields concatenated rows."""
    f5_root = tmp_path / "f5"
    days = [
        (date(2026, 3, d), -3957162.5 + d * 0.0001, 3310203.0, 3737702.0)
        for d in range(1, 31)
    ]
    other = [
        (date(2026, 3, d), -3904422.0 + d * 0.0001, 3484842.0, 3633777.0)
        for d in range(1, 31)
    ]
    _write_synthetic_f5(f5_root, "92110", "2110", "つくば１", "TSUKUBA1", 2026, days)
    _write_synthetic_f5(f5_root, "021098", "1098", "南鳥島", "MINAMI", 2026, other)

    targets = [date(2026, 3, 14), date(2026, 3, 15), date(2026, 3, 16)]
    combined, results = _reference_coords.compute_for_targets(
        targets, f5_root=f5_root, fixed_station_id="92110",
    )
    assert len(results) == 3
    # Each target produces 2 rows (fixed + other) → 6 total.
    assert len(combined) == 6
    assert set(combined["target_date"]) == {t.isoformat() for t in targets}
