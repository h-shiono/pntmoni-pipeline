"""Hex-grid spatial aggregation for monthly performance reports.

Used by the Free Monthly report to render national 95 percentile
horizontal / vertical errors in a CLAS-spec-aligned hex grid
(60 km flat-to-flat). Pro Monthly Detailed will use per-station
scatter instead.

Aggregation rule mirrors methodology §5.1: epoch errors from all
qualified stations in a hex are **pooled**, and the requested
percentile is computed once over the pool. Hex cell value is therefore
a CLAS-spec-aligned spatial slice of the same national pool the
single-number headline figures are computed from, not a median of
per-station values.

Pipeline:
  1. Load station coordinates from the period's reference_coords
     parquet (ECEF) and convert to (lon, lat) under WGS84.
  2. Build a pointy-top hex grid covering Japan at the requested
     flat-to-flat spacing.
  3. Assign each station to the nearest hex center.
  4. Stream per-day epoch_errors parquets, pool by hex, and compute
     the requested percentile per hex.
"""
from __future__ import annotations

import calendar
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# WGS84 ellipsoid — CLAS engine's frame.
_WGS84_A = 6378137.0
_WGS84_F = 1.0 / 298.257223563
_WGS84_E2 = 2 * _WGS84_F - _WGS84_F * _WGS84_F

# Default bbox: tight on the main GEONET footprint — Hokkaido (~46°N)
# to Okinawa (~24°N), Yonaguni (~123°E) to Ogasawara/Hahajima (~142°E).
# The four §4.2 out_of_service southern-ocean stations (Minami-Torishima
# ~154°E, Oki-no-Torishima ~136°E, Iwo-jima ~141°E ~24°N) sit outside
# this bbox by design — they are excluded from evaluation, so they
# carry no hex value to plot.
JAPAN_BBOX = (123.0, 146.0, 24.0, 46.0)

# CLAS spec grid spacing ~60 km (methodology §評価ネットワーク). Default
# hex flat-to-flat matches it for 1:1 visual correspondence with the
# augmentation grid.
DEFAULT_SPACING_KM = 60.0


# --- ECEF → geodetic --------------------------------------------------

def ecef_to_geodetic(
    x: np.ndarray, y: np.ndarray, z: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised ECEF (m) → (lon_deg, lat_deg) under WGS84.

    Iterative latitude solution (Bowring) — converges to sub-mm
    precision in ~4 iterations for terrestrial points.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    p = np.hypot(x, y)
    lon = np.arctan2(y, x)
    # initial guess
    lat = np.arctan2(z, p * (1.0 - _WGS84_E2))
    for _ in range(5):
        sin_lat = np.sin(lat)
        N = _WGS84_A / np.sqrt(1.0 - _WGS84_E2 * sin_lat * sin_lat)
        h = p / np.cos(lat) - N
        lat = np.arctan2(z, p * (1.0 - _WGS84_E2 * N / (N + h)))
    return np.degrees(lon), np.degrees(lat)


# --- Hex grid construction -------------------------------------------

@dataclass(frozen=True)
class HexGrid:
    """Pointy-top hex grid with flat-to-flat spacing in km.

    Layout uses an equirectangular approximation at the bbox mid-
    latitude. Adequate for visualising 1,300-station national
    statistics over Japan; not a true equal-area projection.
    """
    spacing_km: float
    bbox: tuple[float, float, float, float]
    centers: np.ndarray   # (n_hex, 2) -- (lon, lat)

    @property
    def n_hex(self) -> int:
        return int(self.centers.shape[0])

    @property
    def km_per_deg(self) -> tuple[float, float]:
        """(km/deg lat, km/deg lon) at the bbox mid-latitude."""
        lat0 = (self.bbox[2] + self.bbox[3]) / 2.0
        return 111.0, 111.0 * math.cos(math.radians(lat0))

    def vertices(self, hex_idx: int) -> np.ndarray:
        """(6, 2) array of (lon, lat) vertices for the given hex (pointy-top)."""
        cx, cy = self.centers[hex_idx]
        km_lat, km_lon = self.km_per_deg
        r_km = self.spacing_km / math.sqrt(3.0)
        verts = np.empty((6, 2), dtype=np.float64)
        for i in range(6):
            angle = math.radians(60.0 * i - 30.0)
            verts[i, 0] = cx + r_km * math.cos(angle) / km_lon
            verts[i, 1] = cy + r_km * math.sin(angle) / km_lat
        return verts


def make_hex_grid(
    spacing_km: float = DEFAULT_SPACING_KM,
    bbox: tuple[float, float, float, float] = JAPAN_BBOX,
) -> HexGrid:
    """Build a pointy-top hex grid covering the lon/lat bbox.

    Pointy-top hex layout:
      - horizontal center spacing = ``spacing_km`` (flat-to-flat)
      - vertical center spacing   = ``spacing_km * sqrt(3) / 2``
      - every other row is offset by half the horizontal spacing
    """
    lon_min, lon_max, lat_min, lat_max = bbox
    lat0 = (lat_min + lat_max) / 2.0
    km_per_deg_lat = 111.0
    km_per_deg_lon = 111.0 * math.cos(math.radians(lat0))
    d_lon = spacing_km / km_per_deg_lon
    d_lat = spacing_km * math.sqrt(3.0) / 2.0 / km_per_deg_lat

    centers: list[tuple[float, float]] = []
    row = 0
    lat = lat_min
    while lat <= lat_max + 1e-9:
        offset = d_lon / 2.0 if (row % 2) else 0.0
        lon = lon_min + offset
        while lon <= lon_max + 1e-9:
            centers.append((lon, lat))
            lon += d_lon
        lat += d_lat
        row += 1

    return HexGrid(
        spacing_km=spacing_km,
        bbox=bbox,
        centers=np.asarray(centers, dtype=np.float64),
    )


# --- Station coordinates + assignment --------------------------------

def load_station_coords(
    reference_coords_dir: Path,
    *,
    period: str,
    frame_subdir: str = "f5_1",
) -> pd.DataFrame:
    """Load station (lon, lat) from a representative day's reference_coords.

    Uses any day in the period (first available) — station coordinates
    are stable within a month.
    """
    yyyy, mm = int(period[:4]), int(period[5:7])
    n_days = calendar.monthrange(yyyy, mm)[1]
    parquet: Path | None = None
    for d in range(1, n_days + 1):
        p = (
            Path(reference_coords_dir) / frame_subdir / f"{yyyy}"
            / f"{yyyy}{mm:02d}{d:02d}.parquet"
        )
        if p.is_file():
            parquet = p
            break
    if parquet is None:
        # Fallback: try the alternate frame subdir.
        alt = "f5" if frame_subdir != "f5" else "f5_1"
        for d in range(1, n_days + 1):
            p = (
                Path(reference_coords_dir) / alt / f"{yyyy}"
                / f"{yyyy}{mm:02d}{d:02d}.parquet"
            )
            if p.is_file():
                parquet = p
                break
    if parquet is None:
        raise FileNotFoundError(
            f"no reference_coords parquet under {reference_coords_dir} for {period}",
        )

    df = pd.read_parquet(parquet, columns=["rinex_id", "x_m", "y_m", "z_m"])
    df = df.drop_duplicates(subset="rinex_id")
    lon, lat = ecef_to_geodetic(
        df["x_m"].to_numpy(),
        df["y_m"].to_numpy(),
        df["z_m"].to_numpy(),
    )
    return pd.DataFrame({"station": df["rinex_id"].to_numpy(), "lon": lon, "lat": lat})


def assign_stations(
    stations: pd.DataFrame, hex_grid: HexGrid,
    *,
    lon_col: str = "lon", lat_col: str = "lat", id_col: str = "station",
) -> pd.Series:
    """Return Series indexed by station id -> nearest hex_idx."""
    km_per_deg_lat, km_per_deg_lon = hex_grid.km_per_deg
    centers = hex_grid.centers
    s_lon = stations[lon_col].to_numpy()
    s_lat = stations[lat_col].to_numpy()
    # Pairwise distance in km (deg deltas converted via the bbox mid-lat
    # km/deg ratio — fine for our flat-Earth approximation scale).
    dlon_km = (s_lon[:, None] - centers[None, :, 0]) * km_per_deg_lon
    dlat_km = (s_lat[:, None] - centers[None, :, 1]) * km_per_deg_lat
    d2 = dlon_km * dlon_km + dlat_km * dlat_km
    nearest = np.argmin(d2, axis=1)
    return pd.Series(
        nearest.astype(np.int32),
        index=stations[id_col].to_numpy(),
        name="hex_idx",
    )


# --- Aggregation ------------------------------------------------------

def aggregate_epoch_errors_to_hex(
    epoch_errors_dir: Path,
    period: str,
    station_to_hex: pd.Series,
    *,
    percentiles: tuple[float, ...] = (95.0,),
) -> pd.DataFrame:
    """Stream per-day epoch_errors parquets, pool by hex, compute percentiles.

    Returns a DataFrame indexed by hex_idx with columns:
        n_epochs, n_stations,
        horizontal_p{pct}, vertical_p{pct}   (one pair per percentile)
    """
    yyyy, mm = int(period[:4]), int(period[5:7])
    n_days = calendar.monthrange(yyyy, mm)[1]
    hex_map = station_to_hex.to_dict()

    buf_h: dict[int, list[np.ndarray]] = {}
    buf_v: dict[int, list[np.ndarray]] = {}
    counters: dict[int, dict[str, object]] = {}

    cols = ["station", "horizontal_m", "vertical_m"]
    for d in range(1, n_days + 1):
        p = (
            Path(epoch_errors_dir) / f"{yyyy}"
            / f"{yyyy}{mm:02d}{d:02d}.parquet"
        )
        if not p.is_file():
            continue
        df = pd.read_parquet(p, columns=cols)
        df["hex_idx"] = df["station"].map(hex_map)
        df = df.dropna(subset=["hex_idx"])
        if df.empty:
            continue
        df["hex_idx"] = df["hex_idx"].astype(np.int32)
        # Drop NaNs in error columns (defensive — accuracy stats already
        # filters these but day-1 parquets may include diverged epochs).
        df = df.dropna(subset=["horizontal_m", "vertical_m"])
        for hex_idx, sub in df.groupby("hex_idx", sort=False):
            hi = int(hex_idx)
            buf_h.setdefault(hi, []).append(sub["horizontal_m"].to_numpy())
            buf_v.setdefault(hi, []).append(sub["vertical_m"].to_numpy())
            c = counters.setdefault(hi, {"n_epochs": 0, "stations": set()})
            c["n_epochs"] = int(c["n_epochs"]) + int(len(sub))
            c["stations"].update(sub["station"].unique().tolist())

    rows: list[dict[str, object]] = []
    for hex_idx in sorted(buf_h):
        h = np.concatenate(buf_h[hex_idx])
        v = np.concatenate(buf_v[hex_idx])
        row: dict[str, object] = {
            "hex_idx": int(hex_idx),
            "n_epochs": int(counters[hex_idx]["n_epochs"]),
            "n_stations": len(counters[hex_idx]["stations"]),
        }
        for pct in percentiles:
            q = pct / 100.0
            label = int(pct) if float(pct).is_integer() else f"{pct:g}".replace(".", "_")
            row[f"horizontal_p{label}"] = float(np.quantile(h, q))
            row[f"vertical_p{label}"] = float(np.quantile(v, q))
        rows.append(row)

    return pd.DataFrame(rows)


# --- Top-level convenience -------------------------------------------

def build_hex_summary(
    *,
    period: str,
    epoch_errors_dir: Path,
    reference_coords_dir: Path,
    spacing_km: float = DEFAULT_SPACING_KM,
    bbox: tuple[float, float, float, float] = JAPAN_BBOX,
    percentiles: tuple[float, ...] = (95.0,),
    reference_frame_subdir: str = "f5_1",
) -> tuple[HexGrid, pd.DataFrame]:
    """One-shot: grid + station-to-hex + per-hex percentile aggregation.

    Returns the HexGrid plus a DataFrame with one row per *populated*
    hex (empty hexes are absent — the caller draws those as blank).
    """
    grid = make_hex_grid(spacing_km=spacing_km, bbox=bbox)
    stations = load_station_coords(
        reference_coords_dir, period=period, frame_subdir=reference_frame_subdir,
    )
    s2h = assign_stations(stations, grid)
    summary = aggregate_epoch_errors_to_hex(
        epoch_errors_dir, period, s2h, percentiles=percentiles,
    )
    return grid, summary
