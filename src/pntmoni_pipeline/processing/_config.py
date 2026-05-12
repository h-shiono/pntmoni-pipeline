"""Generate a per-station rnx2rtkp config by substituting receiver/antenna."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from ._obs_header import ObsIdentity
from ._station_provenance import StationConfigRecord, record as record_station

logger = logging.getLogger(__name__)


def write_station_config(
    template_path: Path,
    output_path: Path,
    identity: ObsIdentity,
) -> str:
    """Render a per-station config and return the SHA-256 of its content.

    The hash is recorded in :class:`ProcessingResult` so consumers can
    verify the exact configuration used for any solution.
    """
    h = hashlib.sha256()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with template_path.open("r") as fpi, output_path.open("w") as fpo:
        for line in fpi:
            stripped = line.lstrip()
            if stripped.startswith("pos1-rectype"):
                rendered = f"pos1-rectype = {identity.receiver}\n"
            elif stripped.startswith("ant1-anttype"):
                rendered = f"ant1-anttype = {identity.antenna}\n"
            else:
                rendered = line
            fpo.write(rendered)
            h.update(rendered.encode("utf-8"))

    return h.hexdigest()


def record_station_provenance(
    *,
    date_iso: str,
    mode: str,
    station: str,
    identity: ObsIdentity,
    config_hash: str,
    config_path: Path,
    obs_path: Path,
    template_path: Path,
    aux_data_sha256: dict[str, str] | None = None,
    log_path: Path | None = None,
) -> None:
    """Append one row describing this (station, date, mode) processing run.

    ``aux_data_sha256`` lets the caller pass through the hashes of the
    .atx / .erp / .blq / grid files used. The default (empty mapping)
    keeps the row minimal when aux hashes are unknown.
    """
    rec = StationConfigRecord(
        date=date_iso,
        mode=mode,
        station=station,
        receiver=identity.receiver,
        antenna=identity.antenna,
        config_hash=config_hash,
        config_path=str(config_path),
        obs_path=str(obs_path),
        template_path=str(template_path),
        aux_data_sha256=aux_data_sha256 or {},
    )
    record_station(rec, path=log_path)
