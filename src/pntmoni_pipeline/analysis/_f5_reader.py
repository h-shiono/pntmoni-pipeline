"""GSI F5 ``.pos`` daily-coordinate file reader.

F5 files distribute GEONET station coordinates as a daily time series
solved by GSI (Bernese, ITRF2014, GRS80). One file per (station, year)
under ``data/raw/f5/{year}/{F5_ID}.{yy}.pos``. Format::

    +SITE/INF
     ID           000842
     RINEX        0842
     J_NAME       岡部Ａ
     E_NAME       OKABE-A
    -SITE/INF

    +SOLVER/INF
     ...
     COORDINATE   ITRF2014
     ELLIPSOID    GRS80
    -SOLVER/INF

    +DATA
    *yyyy mm dd HH:MM:SS       X (m)         ...
    *----+--+--+--------+-----------------+...
     2026 01 01 12:00:00 -3.9044228500E+06  ...
     ...
    *----+--+--+--------+...
    -DATA

The data block has fixed columns separated by whitespace; we use pandas
to vectorise the load. Rows past the file's published EPOCH/END are
absent (not zero), so callers need to be tolerant of partial windows
when the F5 publication has not caught up to the target date.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

# Number of header lines to skip before the data table starts.
# Counted explicitly against a representative file:
#   1: +SITE/INF                  6: -SITE/INF              13: EPOCH ...
#   2: ID                         7: (blank)                14: COORDINATE ...
#   3: RINEX                      8: +SOLVER/INF            15: ELLIPSOID ...
#   4: J_NAME                     9: SOFT_NAME              16: -SOLVER/INF
#   5: E_NAME                    10: EPHEMERIS              17: (blank)
#                                11: SOLUTION_ID            18: +DATA
#                                12: VERSION                19: *yyyy mm ...
#                                                          20: *----+--+...
F5_HEADER_SKIP = 20
F5_FOOTER_SKIP = 2

F5_DATA_COLUMNS = [
    "year", "month", "day", "hms",
    "x_m", "y_m", "z_m",
    "lat_deg", "lon_deg", "h_m",
]

_SITE_ID_RE = re.compile(r"^\s*ID\s+(\S+)")
_SITE_RINEX_RE = re.compile(r"^\s*RINEX\s+(\S+)")
_SITE_J_NAME_RE = re.compile(r"^\s*J_NAME\s+(.*\S)\s*$")
_SITE_E_NAME_RE = re.compile(r"^\s*E_NAME\s+(.*\S)\s*$")
_COORD_FRAME_RE = re.compile(r"^\s*COORDINATE\s+(\S+)")
_ELLIPSOID_RE = re.compile(r"^\s*ELLIPSOID\s+(\S+)")


@dataclass(frozen=True)
class F5Metadata:
    """SITE/INF and SOLVER/INF block contents from one F5 file."""
    f5_id: str
    rinex_id: str
    j_name: str
    e_name: str
    frame: str           # e.g. "ITRF2014"
    ellipsoid: str       # e.g. "GRS80"


@dataclass(frozen=True)
class F5Station:
    """One station's daily coordinates parsed from a single F5 ``.pos``."""
    metadata: F5Metadata
    df: pd.DataFrame     # columns: date (datetime64[ns]), x_m, y_m, z_m, lat_deg, lon_deg, h_m
    file_path: Path
    sha256: str


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_metadata(path: Path) -> F5Metadata:
    """Walk the header until ``+DATA`` and extract identification + frame."""
    fields: dict[str, str] = {}
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("+DATA"):
                break
            for key, regex in (
                ("f5_id", _SITE_ID_RE),
                ("rinex_id", _SITE_RINEX_RE),
                ("j_name", _SITE_J_NAME_RE),
                ("e_name", _SITE_E_NAME_RE),
                ("frame", _COORD_FRAME_RE),
                ("ellipsoid", _ELLIPSOID_RE),
            ):
                if key in fields:
                    continue
                m = regex.match(line)
                if m:
                    fields[key] = m.group(1)
    missing = [k for k in ("f5_id", "rinex_id", "frame") if k not in fields]
    if missing:
        raise ValueError(f"F5 metadata fields missing in {path}: {missing}")
    return F5Metadata(
        f5_id=fields["f5_id"],
        rinex_id=fields["rinex_id"],
        j_name=fields.get("j_name", ""),
        e_name=fields.get("e_name", ""),
        frame=fields["frame"],
        ellipsoid=fields.get("ellipsoid", ""),
    )


def read_f5(path: Path) -> F5Station:
    """Parse one F5 ``.pos`` file into header metadata + daily series."""
    md = _parse_metadata(path)

    # The DATA block separates columns by variable whitespace; pandas
    # handles this via sep=r"\s+" / engine="python" with skipfooter.
    df = pd.read_csv(
        path,
        sep=r"\s+",
        skiprows=F5_HEADER_SKIP,
        skipfooter=F5_FOOTER_SKIP,
        names=F5_DATA_COLUMNS,
        engine="python",
        comment="*",                 # tolerate stray separator/header markers
    )
    if df.empty:
        return F5Station(
            metadata=md, df=df.assign(date=pd.NaT)[["date", "x_m", "y_m", "z_m", "lat_deg", "lon_deg", "h_m"]],
            file_path=path,
            sha256=_sha256(path),
        )

    # Build a single ``date`` column (UTC midnight; F5 publishes 12:00:00
    # UTC but for daily comparisons we anchor the index to the calendar
    # day, not the time-of-day).
    df["date"] = pd.to_datetime(
        df["year"].astype(str)
        + "-" + df["month"].astype(str).str.zfill(2)
        + "-" + df["day"].astype(str).str.zfill(2),
        format="%Y-%m-%d",
        utc=True,
    )
    df = df[["date", "x_m", "y_m", "z_m", "lat_deg", "lon_deg", "h_m"]].reset_index(drop=True)
    return F5Station(metadata=md, df=df, file_path=path, sha256=_sha256(path))


def f5_path(root: Path, f5_id: str, year: int) -> Path:
    """Return the conventional ``data/raw/f5/{year}/{F5_ID}.{yy}.pos`` path."""
    yy = f"{year % 100:02d}"
    return root / f"{year}" / f"{f5_id}.{yy}.pos"


def list_f5_files(root: Path, year: int) -> list[Path]:
    """All F5 ``.pos`` files under ``root/{year}/``. Sorted for determinism."""
    return sorted((root / f"{year}").glob("*.pos"))


def date_range(target: date, window_days: int) -> tuple[date, date]:
    """Return ``(target - window_days, target + window_days)`` inclusive."""
    return (target - timedelta(days=window_days), target + timedelta(days=window_days))


__all__ = [
    "F5_DATA_COLUMNS",
    "F5_FOOTER_SKIP",
    "F5_HEADER_SKIP",
    "F5Metadata",
    "F5Station",
    "date_range",
    "f5_path",
    "list_f5_files",
    "read_f5",
]
