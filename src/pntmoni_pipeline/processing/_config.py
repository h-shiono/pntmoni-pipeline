"""Generate a per-station rnx2rtkp config by substituting receiver/antenna."""
from __future__ import annotations

import hashlib
from pathlib import Path

from ._obs_header import ObsIdentity


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
