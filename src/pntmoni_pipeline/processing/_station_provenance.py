"""Per-station processing provenance JSONL log.

Captures rectype/anttype/config_hash + the SHA-256s of every aux data
file referenced by the per-station config, indexed by (date, mode,
station). Downstream consumers can join this against
``processing.jsonl`` for full audit traceability without parsing the
per-station ``.conf`` files.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PROVENANCE_PATH = Path("data/metadata/station_config.jsonl")


@dataclass(frozen=True)
class StationConfigRecord:
    """One record per (station, date, mode) processing run."""

    date: str
    mode: str
    station: str
    receiver: str
    antenna: str
    config_hash: str
    config_path: str
    obs_path: str
    template_path: str
    aux_data_sha256: dict[str, str] = field(default_factory=dict)
    recorded_at: str = ""

    def to_jsonable(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def record(rec: StationConfigRecord, path: Path | None = None) -> Path:
    """Append one record to the JSONL log. Returns the path written to."""
    out = path or DEFAULT_PROVENANCE_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    if not rec.recorded_at:
        rec = StationConfigRecord(
            **{**asdict(rec), "recorded_at": datetime.now(UTC).isoformat()},
        )
    line = json.dumps(rec.to_jsonable(), ensure_ascii=False)
    with out.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    logger.debug("recorded station config provenance: %s/%s", rec.station, rec.date)
    return out
