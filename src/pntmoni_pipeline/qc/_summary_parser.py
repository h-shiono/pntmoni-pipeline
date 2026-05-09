"""Parse a teqc ``.{yy}S`` QC summary into structured data.

Port of the canonical reader in
``gnss_research_toolbox/utils/station_analysis.py``. Returns a
:class:`StationQCSummary` whose flat representation matches the
column ordering the legacy ``summary.csv`` used. Column-position
slicing is preserved verbatim (teqc output is fixed-width).

The summary is structured as:

- Header — receiver / antenna identification, approximate position,
  observation counters.
- Body — per-elevation-window blocks, three signal kinds:
    ION  (1 block):  ``tot, slps, rms``
    MP   (6 blocks): MP12, MP21, MP15, MP51, MP17, MP71 — ``tot, slps, rms``
    SN   (4 blocks): SN1, SN2, SN5, SN7 — ``tot, sig, mean``

Each block has 19 elevation windows from "85 - 90" down to "   <  0".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from io import TextIOBase
from pathlib import Path

ELEVATION_WINDOWS: tuple[str, ...] = (
    "85 - 90", "80 - 85", "75 - 80", "70 - 75", "65 - 70",
    "60 - 65", "55 - 60", "50 - 55", "45 - 50", "40 - 45",
    "35 - 40", "30 - 35", "25 - 30", "20 - 25", "15 - 20",
    "10 - 15", " 5 - 10", " 0 -  5", "   <  0",
)
N_ELEVATION = len(ELEVATION_WINDOWS)

MP_KEYS: tuple[str, ...] = ("MP12", "MP21", "MP15", "MP51", "MP17", "MP71")
SN_KEYS: tuple[str, ...] = ("SN1", "SN2", "SN5", "SN7")

_REC_NUM_RE = re.compile(r"\(# = ([0-9A-Za-z\-\.]+)\)")
_REC_FW_RE = re.compile(r"\(fw = (.+?)\)")


@dataclass
class StationQCSummary:
    id: str = ""
    rec_type: str = ""
    rec_num: str = ""
    rec_fw_ver: str = ""
    ant_type: str = ""
    approx_pos_x: float = 0.0
    approx_pos_y: float = 0.0
    approx_pos_z: float = 0.0
    visibility: float = 0.0
    epochs_w_obs: int = 0
    # Per-elev: {elev_window: (tot, slps_or_sig, rms_or_mean)}
    ion: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    mp: dict[str, dict[str, tuple[float, float, float]]] = field(default_factory=dict)
    sn: dict[str, dict[str, tuple[float, float, float]]] = field(default_factory=dict)


def _parse_header(fp: TextIOBase, summary: StationQCSummary) -> None:
    n_possible = 0
    n_complete = 0
    for line in fp:
        if "4-character ID" in line:
            summary.id = line.split(":")[1].strip()
        elif "Receiver type" in line:
            payload = line.split(":", 1)[1].strip()
            summary.rec_type = payload.split("(")[0].strip()
            m_num = _REC_NUM_RE.search(payload)
            m_fw = _REC_FW_RE.search(payload)
            summary.rec_num = m_num.group(1) if m_num else ""
            summary.rec_fw_ver = m_fw.group(1) if m_fw else ""
        elif "Antenna type" in line:
            summary.ant_type = line.split(":")[1].strip()
        elif "Epochs w/ observations" in line:
            summary.epochs_w_obs = int(line.split(":")[1].strip())
        elif "antenna WGS 84 (xyz)" in line:
            xyz = line.split(":")[1].strip().split()[:3]
            summary.approx_pos_x = float(xyz[0])
            summary.approx_pos_y = float(xyz[1])
            summary.approx_pos_z = float(xyz[2])
        elif "Possible obs >  10.0 deg" in line:
            n_possible = int(line.split(":")[1].strip())
        elif "Complete obs >  10.0 deg" in line:
            n_complete = int(line.split(":")[1].strip())
            summary.visibility = (n_complete / n_possible) if n_possible else 0.0
        elif "Observation interval :" in line:
            return


def _parse_elev_row_3floats(line: str) -> tuple[str, float, float, float]:
    """Return (elev_window_label, col0, col1, col2) from a fixed-width data row.

    Per teqc's column layout (matches ``station_analysis.py``):
        line[1:8]    elevation window label (e.g. "85 - 90")
        line[10:15]  total observation count
        line[16:23]  slips (ION/MP) or sig (SN) — wider field for SN
        line[21:31]  rms (ION/MP) at fixed cols
        line[24:32]  mean (SN) at fixed cols
    """
    raise RuntimeError("use the kind-specific parser below")


def _parse_ion_row(line: str) -> tuple[str, float, float, float]:
    return (
        line[1:8],
        float(line[10:15]),
        float(line[16:20]),
        float(line[21:31]),
    )


def _parse_mp_row(line: str) -> tuple[str, float, float, float]:
    return (
        line[1:8],
        float(line[10:15]),
        float(line[16:20]),
        float(line[21:31]),
    )


def _parse_sn_row(line: str) -> tuple[str, float, float, float]:
    return (
        line[1:8],
        float(line[10:15]),
        float(line[16:23]),
        float(line[24:32]),
    )


def _read_block(
    fp: TextIOBase, kind: str,
) -> dict[str, tuple[float, float, float]]:
    """Read 19 elevation rows after a block header. ``kind`` ∈ {'ion','mp','sn'}."""
    parser = {"ion": _parse_ion_row, "mp": _parse_mp_row, "sn": _parse_sn_row}[kind]
    rows: dict[str, tuple[float, float, float]] = {}
    for _ in range(N_ELEVATION):
        line = fp.readline()
        if not line:
            break
        elev, a, b, c = parser(line)
        rows[elev] = (a, b, c)
    return rows


def _parse_body(fp: TextIOBase, summary: StationQCSummary) -> None:
    for line in fp:
        if "elev (deg)  tot" in line:
            if "ION" in line:
                summary.ion = _read_block(fp, "ion")
            elif "MP" in line:
                key = line[22:26].strip()
                if key in MP_KEYS:
                    summary.mp[key] = _read_block(fp, "mp")
            elif "SN" in line:
                key = line[16:19].strip()
                if key in SN_KEYS:
                    summary.sn[key] = _read_block(fp, "sn")


def parse_teqc_summary(path: Path) -> StationQCSummary:
    """Parse one teqc ``.{yy}S`` summary file."""
    s = StationQCSummary()
    with path.open("r", encoding="utf-8", errors="replace") as fp:
        _parse_header(fp, s)
        _parse_body(fp, s)
    return s


# ---------------------------------------------------------------------------
# Wide-row flattening (matches legacy summary.csv column order)
# ---------------------------------------------------------------------------

def _elev_key(elev: str) -> str:
    return elev.replace(" ", "_")


def wide_columns() -> list[str]:
    """Column ordering compatible with legacy ``summary.csv``."""
    cols: list[str] = [
        "id", "rec_type", "rec_num", "rec_fw_ver", "ant_type",
        "approx_pos_x", "approx_pos_y", "approx_pos_z",
        "visibility", "epochs_w_obs",
    ]
    for axis_name in ("tot", "slps", "rms"):
        for elev in ELEVATION_WINDOWS:
            cols.append(f"ION_{_elev_key(elev)}_{axis_name}")
    for mp in MP_KEYS:
        for axis_name in ("tot", "slps", "rms"):
            for elev in ELEVATION_WINDOWS:
                cols.append(f"{mp}_{_elev_key(elev)}_{axis_name}")
    for sn in SN_KEYS:
        for axis_name in ("tot", "sig", "mean"):
            for elev in ELEVATION_WINDOWS:
                cols.append(f"{sn}_{_elev_key(elev)}_{axis_name}")
    return cols


def to_wide_row(s: StationQCSummary) -> dict[str, object]:
    """Flatten ``StationQCSummary`` to a dict keyed by :func:`wide_columns`."""
    row: dict[str, object] = {
        "id": s.id,
        "rec_type": s.rec_type,
        "rec_num": s.rec_num,
        "rec_fw_ver": s.rec_fw_ver,
        "ant_type": s.ant_type,
        "approx_pos_x": s.approx_pos_x,
        "approx_pos_y": s.approx_pos_y,
        "approx_pos_z": s.approx_pos_z,
        "visibility": s.visibility,
        "epochs_w_obs": s.epochs_w_obs,
    }
    nan = float("nan")
    for axis_idx, axis_name in enumerate(("tot", "slps", "rms")):
        for elev in ELEVATION_WINDOWS:
            v = s.ion.get(elev)
            row[f"ION_{_elev_key(elev)}_{axis_name}"] = v[axis_idx] if v else nan
    for mp in MP_KEYS:
        block = s.mp.get(mp, {})
        for axis_idx, axis_name in enumerate(("tot", "slps", "rms")):
            for elev in ELEVATION_WINDOWS:
                v = block.get(elev)
                row[f"{mp}_{_elev_key(elev)}_{axis_name}"] = v[axis_idx] if v else nan
    for sn in SN_KEYS:
        block = s.sn.get(sn, {})
        for axis_idx, axis_name in enumerate(("tot", "sig", "mean")):
            for elev in ELEVATION_WINDOWS:
                v = block.get(elev)
                row[f"{sn}_{_elev_key(elev)}_{axis_name}"] = v[axis_idx] if v else nan
    return row


__all__ = [
    "ELEVATION_WINDOWS",
    "MP_KEYS",
    "N_ELEVATION",
    "SN_KEYS",
    "StationQCSummary",
    "parse_teqc_summary",
    "to_wide_row",
    "wide_columns",
]
