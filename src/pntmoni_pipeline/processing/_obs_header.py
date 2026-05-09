"""Read receiver and antenna identifiers from a RINEX OBS header.

``rnx2rtkp`` does not auto-detect newer GEONET antenna types unless the
config file's ``pos1-rectype`` and ``ant1-anttype`` fields are populated
explicitly. We extract these from the obs file header and substitute
them into a per-station config (mirroring the legacy script's behaviour).
"""
from __future__ import annotations

import gzip
from dataclasses import dataclass
from pathlib import Path


# RINEX 2/3 reserves columns 60+ for the label name (e.g. "REC # / TYPE / VERS").
# Fields preceding it are fixed-width, 20 chars each.
_LABEL_COL = 60
_FIELD_WIDTH = 20


@dataclass(frozen=True)
class ObsIdentity:
    receiver: str               # "{rec_no:<20}{rec_type:<20}{rec_vers:<20}" → take cols 20-40
    antenna: str                # cols 20-40 of "ANT # / TYPE", radome forced to NONE


def _open_obs(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", errors="replace")
    return path.open("r", errors="replace")


def read_identity(obs_path: Path) -> ObsIdentity:
    """Parse the receiver and antenna types from the obs header.

    The ``ant1-anttype`` field rnx2rtkp expects has the form
    ``"<antenna_model><pad>NONE"`` where the radome name is forced to
    ``NONE``. We mirror the legacy script: take chars 20-40 of the
    ``ANT # / TYPE`` line and replace cols 16-20 (radome) with ``NONE``.
    """
    receiver: str | None = None
    antenna: str | None = None

    with _open_obs(obs_path) as fp:
        for line in fp:
            label = line[_LABEL_COL:].strip()
            if label.startswith("REC # / TYPE / VERS"):
                receiver = line[_FIELD_WIDTH:_FIELD_WIDTH * 2]
            elif label.startswith("ANT # / TYPE"):
                ant = line[_FIELD_WIDTH:_FIELD_WIDTH * 2]
                # Force radome to NONE (cols 16-20) per CLASLIB convention.
                antenna = (ant[:16] + "NONE")
            if label.startswith("END OF HEADER"):
                break

    if receiver is None or antenna is None:
        missing = [
            name for name, val in (("receiver", receiver), ("antenna", antenna))
            if val is None
        ]
        raise ValueError(
            f"RINEX header in {obs_path} is missing fields: {', '.join(missing)}"
        )

    return ObsIdentity(receiver=receiver, antenna=antenna)
