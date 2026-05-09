"""Geodetic / ECEF / ENU coordinate transforms (WGS-84).

Mirrors the legacy gnss_research_toolbox common math: ``blh2xyz``,
``xyz2blh``, ``xyz2enu``. Constants match RTKLIB's WGS-84 definition.

All angle inputs to the public functions are in **radians**. Use
:func:`deg2rad` / :func:`rad2deg` (numpy) at the boundary if you have
degrees. ``dm2deg`` converts NMEA's ``dddmm.mmmm`` form to decimal
degrees.

Mode-specific accuracy thresholds for the strict TTFF criterion
``Q == 4 AND horizontal_m <= H AND vertical_m <= V`` are also defined
here, matching legacy ``KINEMATIC_H/V`` and ``STATIC_H/V``.
"""
from __future__ import annotations

from typing import NamedTuple

import numpy as np

# WGS-84 (RTKLIB convention).
WGS84_A = 6_378_137.0                    # semi-major axis [m]
WGS84_F = 1.0 / 298.257_223_563          # flattening
WGS84_B = WGS84_A * (1.0 - WGS84_F)      # semi-minor axis [m]
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)     # eccentricity squared
WGS84_E = float(np.sqrt(WGS84_E2))

# GPST − UTC seconds as of 2026 (next leap second event TBD).
LEAP_SECONDS = 18

# TTFF strict-criterion thresholds (m). Legacy values from
# gnss_research_toolbox/common.py.
KINEMATIC_H = 0.12
KINEMATIC_V = 0.24
STATIC_H = 0.06
STATIC_V = 0.12


class TTFFThresholds(NamedTuple):
    horizontal_m: float
    vertical_m: float


def thresholds_for_mode(mode: str) -> TTFFThresholds:
    """Pick (H, V) based on the engine config-mode label.

    Heuristic on the mode name (``kinematic``/``static`` substring), so
    arbitrary mode names like ``kinematic_p30_ttff_verify`` resolve to
    the kinematic thresholds. Override callers should pass explicit
    values rather than rely on the heuristic.
    """
    m = mode.lower()
    if "kinematic" in m:
        return TTFFThresholds(KINEMATIC_H, KINEMATIC_V)
    if "static" in m:
        return TTFFThresholds(STATIC_H, STATIC_V)
    raise ValueError(
        f"cannot infer kinematic/static from mode={mode!r}; pass thresholds explicitly"
    )


def dm2deg(dm: float) -> float:
    """Convert NMEA degree-minute (``dddmm.mmmm``) to decimal degrees."""
    deg = int(dm / 100)
    minutes = dm - deg * 100
    return deg + minutes / 60.0


def blh_rad_to_xyz(b: float, l: float, h: float) -> np.ndarray:
    """Geodetic (lat, lon in **radians**, height in m) → ECEF (X, Y, Z)."""
    n = WGS84_A / np.sqrt(1.0 - WGS84_E2 * np.sin(b) ** 2)
    x = (n + h) * np.cos(b) * np.cos(l)
    y = (n + h) * np.cos(b) * np.sin(l)
    z = (n * (1.0 - WGS84_E2) + h) * np.sin(b)
    return np.array([x, y, z])


def xyz_to_blh_rad(xyz: np.ndarray) -> np.ndarray:
    """ECEF → Geodetic (lat, lon in **radians**, height in m)."""
    x, y, z = xyz
    h_diff = WGS84_A ** 2 - WGS84_B ** 2
    p = np.sqrt(x ** 2 + y ** 2)
    t = np.arctan2(z * WGS84_A, p * WGS84_B)
    lat = np.arctan2(
        z + h_diff / WGS84_B * np.sin(t) ** 3,
        p - h_diff / WGS84_A * np.cos(t) ** 3,
    )
    n = WGS84_A / np.sqrt(1.0 - WGS84_E2 * np.sin(lat) ** 2)
    lon = np.arctan2(y, x)
    h = (p / np.cos(lat)) - n
    return np.array([lat, lon, h])


def xyz_to_enu(xyz_rover: np.ndarray, xyz_base: np.ndarray) -> np.ndarray:
    """ECEF rover relative to ECEF base → local ENU (m).

    Vectorised over the leading axis: pass an ``(N, 3)`` array of rover
    positions and a single ``(3,)`` base; result is ``(N, 3)``.
    """
    rover = np.asarray(xyz_rover)
    base = np.asarray(xyz_base)
    diff = rover - base
    blh_base = xyz_to_blh_rad(base)
    s_l = np.sin(blh_base[1])
    c_l = np.cos(blh_base[1])
    s_b = np.sin(blh_base[0])
    c_b = np.cos(blh_base[0])
    if diff.ndim == 1:
        e = -diff[0] * s_l + diff[1] * c_l
        n = -diff[0] * c_l * s_b - diff[1] * s_l * s_b + diff[2] * c_b
        u = diff[0] * c_l * c_b + diff[1] * s_l * c_b + diff[2] * s_b
        return np.array([e, n, u])
    e = -diff[:, 0] * s_l + diff[:, 1] * c_l
    n = -diff[:, 0] * c_l * s_b - diff[:, 1] * s_l * s_b + diff[:, 2] * c_b
    u = diff[:, 0] * c_l * c_b + diff[:, 1] * s_l * c_b + diff[:, 2] * s_b
    return np.column_stack([e, n, u])


def blh_deg_to_xyz_array(blh_deg: np.ndarray) -> np.ndarray:
    """Vectorised geodetic-deg → ECEF for ``(N, 3)`` arrays.

    ``blh_deg[:, 0]`` = lat (deg), ``blh_deg[:, 1]`` = lon (deg),
    ``blh_deg[:, 2]`` = height (m).
    """
    blh = np.asarray(blh_deg, dtype=np.float64)
    if blh.ndim == 1:
        b, l, h = np.deg2rad(blh[0]), np.deg2rad(blh[1]), float(blh[2])
        return blh_rad_to_xyz(b, l, h)
    b = np.deg2rad(blh[:, 0])
    l = np.deg2rad(blh[:, 1])
    h = blh[:, 2]
    n = WGS84_A / np.sqrt(1.0 - WGS84_E2 * np.sin(b) ** 2)
    x = (n + h) * np.cos(b) * np.cos(l)
    y = (n + h) * np.cos(b) * np.sin(l)
    z = (n * (1.0 - WGS84_E2) + h) * np.sin(b)
    return np.column_stack([x, y, z])


__all__ = [
    "KINEMATIC_H", "KINEMATIC_V", "STATIC_H", "STATIC_V",
    "LEAP_SECONDS",
    "TTFFThresholds",
    "WGS84_A", "WGS84_B", "WGS84_E2", "WGS84_F",
    "blh_deg_to_xyz_array",
    "blh_rad_to_xyz",
    "dm2deg",
    "thresholds_for_mode",
    "xyz_to_blh_rad",
    "xyz_to_enu",
]
