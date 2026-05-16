"""Stage 1: per-epoch ENU errors from CLASLIB ``.pos`` output.

Reads NMEA ``$GPRMC`` + ``$GPGGA`` pairs from ``.pos`` files produced
by the processing layer, joins each station to its 15-day-median
reference coordinate from ``data/processed/reference_coords/...``,
and writes one Parquet per (mode, year, doy) containing every epoch
of every station with the full long-format schema:

    date, station, mode, engine_version,
    epoch_idx, time_utc, quality, num_sat,
    e_m, n_m, u_m, horizontal_m, vertical_m, is_day

This Parquet is the canonical input for both the accuracy and TTFF
Stage-2 aggregators.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from . import _coords_math
from . import _f5_reader  # not used directly but keeps the namespace warm  # noqa: F401

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_ROOT = Path("data/processed/epoch_errors")
DEFAULT_REF_COORDS_ROOT = Path("data/processed/reference_coords")
DEFAULT_PROCESSED_ROOT = Path("data/processed")
DEFAULT_PROVENANCE_PATH = Path("data/metadata/epoch_errors.jsonl")

# Day window (UTC) matches legacy: night = UTC 10..20, otherwise day.
DAY_HOURS_UTC: frozenset[int] = frozenset(set(range(0, 10)) | set(range(21, 24)))


@dataclass(frozen=True)
class EpochErrorsResult:
    parquet_path: Path
    n_stations: int
    n_epochs: int
    ref_coords_source: Path
    target_date: date
    mode: str
    engine_version: str


# ---------------------------------------------------------------------------
# .pos NMEA parsing
# ---------------------------------------------------------------------------

def parse_pos_nmea(pos_path: Path, *, leap_seconds: int = _coords_math.LEAP_SECONDS) -> pd.DataFrame:
    """Parse a ``.pos`` (NMEA $GPRMC + $GPGGA pairs) into a DataFrame.

    Columns: ``time_utc`` (datetime64[ns, UTC]), ``epoch_idx`` (int —
    GPST seconds-of-day // 30 with 30 s sampling assumption), ``quality``
    (int8), ``num_sat`` (int8), ``lat_deg``, ``lon_deg``, ``alt_m``.

    Missing $GPRMC for an epoch falls back to deriving the date from the
    file's surrounding context; we re-use the most recent $GPRMC date.
    """
    rows: list[tuple] = []
    current_date: str | None = None
    current_time: str | None = None
    with pos_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("$GPRMC"):
                parts = line.rstrip().split(",")
                # $GPRMC,hhmmss.ss,A,lat,N,lon,E,sog,cog,ddmmyy,...
                if len(parts) >= 10:
                    current_time = parts[1]
                    current_date = parts[9]
            elif line.startswith("$GPGGA"):
                parts = line.rstrip().split(",")
                # $GPGGA,hhmmss.ss,lat,N,lon,E,Q,nsat,hdop,alt,M,geoid,M,...
                if len(parts) < 12 or current_date is None:
                    continue
                hms = parts[1]
                if not hms:
                    continue
                lat_dm = parts[2]
                lat_ns = parts[3]
                lon_dm = parts[4]
                lon_ew = parts[5]
                q_str = parts[6]
                nsat_str = parts[7]
                alt_str = parts[9]
                geoid_str = parts[11]
                if not lat_dm or not lon_dm or not q_str or not nsat_str:
                    continue
                # NMEA UTC date+time → GPST timestamp
                t_utc = datetime.strptime(
                    f"{current_date}{hms}", "%d%m%y%H%M%S.%f",
                ).replace(tzinfo=UTC)
                t_gpst = t_utc + timedelta(seconds=leap_seconds)
                lat = _coords_math.dm2deg(float(lat_dm)) * (-1 if lat_ns == "S" else 1)
                lon = _coords_math.dm2deg(float(lon_dm)) * (-1 if lon_ew == "W" else 1)
                quality = int(q_str)
                num_sat = int(nsat_str)
                alt = float(alt_str) + (float(geoid_str) if geoid_str else 0.0)
                rows.append((t_utc, t_gpst, lat, lon, alt, quality, num_sat))

    if not rows:
        return pd.DataFrame(columns=[
            "time_utc", "time_gpst", "lat_deg", "lon_deg", "alt_m",
            "quality", "num_sat", "epoch_idx",
        ])

    df = pd.DataFrame(rows, columns=[
        "time_utc", "time_gpst", "lat_deg", "lon_deg", "alt_m", "quality", "num_sat",
    ])
    # epoch_idx = GPST-seconds-of-day // 30 (works for the 30-s-sampled
    # CLASLIB output we produce; the same convention as analysis/_ttff).
    sod = (
        df["time_gpst"].dt.hour * 3600
        + df["time_gpst"].dt.minute * 60
        + df["time_gpst"].dt.second
    )
    df["epoch_idx"] = (sod // 30).astype("int32")
    df["quality"] = df["quality"].astype("int8")
    df["num_sat"] = df["num_sat"].astype("int8")
    return df


# ---------------------------------------------------------------------------
# Reference-coords lookup
# ---------------------------------------------------------------------------

def find_reference_coords_parquet(
    target: date,
    *,
    root: Path = DEFAULT_REF_COORDS_ROOT,
    variant: str | None = None,
) -> Path:
    """Locate the reference-coords Parquet that contains rows for ``target``.

    Output layout is variant-namespaced
    (``{root}/{variant}/{year}/{...}.parquet``) so the Monthly 速報 (R5/R5.1)
    and 続報 (F5/F5.1) snapshots coexist for the same target date.

    Search order within ``{root}/{variant}/``: daily
    ``{year}/{YYYYMMDD}.parquet`` first, then weekly
    ``{year}/W{ww}.parquet`` where the target date's ISO-week matches.

    Auto-resolution when ``variant is None``: prefer the final (續報) lineage
    over the rapid (速報) one if both exist — F5.1, F5, R5.1, R5 in that
    order. This matches the "use the most rigorous reference available"
    semantics; callers wanting an explicit rapid lookup must pass
    ``variant="r5_1"``.
    """
    variants = [variant] if variant else ("f5_1", "f5", "r5_1", "r5")
    tried: list[Path] = []
    for v in variants:
        year_dir = root / v / f"{target.year}"
        daily = year_dir / f"{target.strftime('%Y%m%d')}.parquet"
        if daily.is_file():
            return daily
        iso_year, iso_week, _ = target.isocalendar()
        weekly = root / v / f"{iso_year}" / f"W{iso_week:02d}.parquet"
        if weekly.is_file():
            return weekly
        tried.extend([daily, weekly])
    raise FileNotFoundError(
        f"no reference_coords Parquet found for {target} under {root}; "
        f"tried {tried}"
    )


def load_reference_coords_for_target(
    target: date, *, ref_coords_path: Path,
) -> pd.DataFrame:
    """Read the Parquet and filter to rows whose ``target_date`` matches."""
    df = pd.read_parquet(ref_coords_path)
    df = df[df["target_date"] == target.isoformat()].reset_index(drop=True)
    if df.empty:
        raise RuntimeError(
            f"reference_coords {ref_coords_path} has no rows for target_date={target}"
        )
    return df


# ---------------------------------------------------------------------------
# Stage 1 main
# ---------------------------------------------------------------------------

def list_pos_files(processed_root: Path, mode: str, target: date) -> list[Path]:
    doy = int(target.strftime("%j"))
    return sorted((processed_root / mode / f"{target.year}" / f"{doy:03d}").glob("*.pos"))


def compute_epoch_errors(
    target: date,
    *,
    mode: str,
    processed_root: Path = DEFAULT_PROCESSED_ROOT,
    ref_coords_path: Path | None = None,
    ref_variant: str | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    engine_version: str = "unknown",
    stations: Iterable[str] | None = None,
    record_provenance: bool = True,
    provenance_path: Path | None = None,
) -> EpochErrorsResult:
    """Build epoch_errors Parquet for one DOY × all (or filtered) stations."""
    if ref_coords_path is None:
        ref_coords_path = find_reference_coords_parquet(target, variant=ref_variant)
    ref = load_reference_coords_for_target(target, ref_coords_path=ref_coords_path)
    ref_xyz_by_rinex = {
        row.rinex_id: np.array([row.x_m, row.y_m, row.z_m])
        for row in ref.itertuples(index=False)
    }

    pos_files = list_pos_files(processed_root, mode, target)
    if stations is not None:
        wanted = set(stations)
        pos_files = [p for p in pos_files if p.name[:4] in wanted]
    if not pos_files:
        raise FileNotFoundError(f"no .pos files for {target} under {processed_root / mode}")

    all_rows: list[pd.DataFrame] = []
    n_skipped = 0
    for pos in pos_files:
        station = pos.name[:4]
        ref_xyz = ref_xyz_by_rinex.get(station)
        if ref_xyz is None:
            logger.debug("station %s has no reference coord; skipping", station)
            n_skipped += 1
            continue
        df = parse_pos_nmea(pos)
        if df.empty:
            n_skipped += 1
            continue
        rover_xyz = _coords_math.blh_deg_to_xyz_array(
            df[["lat_deg", "lon_deg", "alt_m"]].to_numpy()
        )
        enu = _coords_math.xyz_to_enu(rover_xyz, ref_xyz)
        df["e_m"] = enu[:, 0].astype("float32")
        df["n_m"] = enu[:, 1].astype("float32")
        df["u_m"] = enu[:, 2].astype("float32")
        df["horizontal_m"] = np.hypot(df["e_m"], df["n_m"]).astype("float32")
        df["vertical_m"] = np.abs(df["u_m"]).astype("float32")
        df["station"] = station
        df["mode"] = mode
        df["engine_version"] = engine_version
        df["date"] = target.isoformat()
        df["is_day"] = df["time_utc"].dt.hour.isin(DAY_HOURS_UTC)
        all_rows.append(df[[
            "date", "station", "mode", "engine_version",
            "epoch_idx", "time_utc", "quality", "num_sat",
            "e_m", "n_m", "u_m", "horizontal_m", "vertical_m", "is_day",
        ]])

    if not all_rows:
        raise RuntimeError(f"no valid epoch rows produced for {target}")

    combined = pd.concat(all_rows, ignore_index=True)
    out_path = output_root / mode / f"{target.year}" / f"{target.strftime('%Y%m%d')}.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(out_path, index=False)

    result = EpochErrorsResult(
        parquet_path=out_path,
        n_stations=combined["station"].nunique(),
        n_epochs=len(combined),
        ref_coords_source=ref_coords_path,
        target_date=target,
        mode=mode,
        engine_version=engine_version,
    )

    logger.info(
        "epoch_errors: wrote %s (%d stations, %d epochs)",
        out_path, result.n_stations, result.n_epochs,
    )
    if n_skipped:
        logger.info("skipped %d station(s) (no ref coord or empty .pos)", n_skipped)

    if record_provenance:
        _record_provenance(result, provenance_path or DEFAULT_PROVENANCE_PATH, n_skipped)

    return result


def _record_provenance(
    res: EpochErrorsResult, path: Path, n_skipped: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "target_date": res.target_date.isoformat(),
        "mode": res.mode,
        "engine_version": res.engine_version,
        "n_stations": res.n_stations,
        "n_epochs": res.n_epochs,
        "n_stations_skipped": n_skipped,
        "ref_coords_source": str(res.ref_coords_source),
        "output_parquet": str(res.parquet_path),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


__all__ = [
    "DAY_HOURS_UTC",
    "EpochErrorsResult",
    "compute_epoch_errors",
    "find_reference_coords_parquet",
    "list_pos_files",
    "parse_pos_nmea",
]
