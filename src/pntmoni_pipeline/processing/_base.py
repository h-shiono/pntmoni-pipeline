"""Processing primitives: result dataclass and shared types."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProcessingResult:
    """One station's CLASLIB processing outcome.

    The ``.pos`` solution file is the canonical artifact. ``.trace`` and
    per-station ``.conf`` are kept alongside for audit and debugging.
    """

    engine: str                 # "claslib" | "mrtklib" (future)
    engine_version: str         # CLASLIB revision string, e.g. "Rev.L"
    mode: str                   # config mode name, e.g. "kinematic_p30"
    config_hash: str            # SHA-256 of the per-station config
    station: str                # 4-char GEONET station ID
    date: str                   # ISO date YYYY-MM-DD
    pos_path: Path              # data/processed/{mode}/{year}/{doy}/{station}{doy}0.pos
    trace_path: Path | None
    config_path: Path | None
    started_at: datetime
    finished_at: datetime
    duration_sec: float
    skipped: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_jsonable(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("pos_path", "trace_path", "config_path"):
            if d[k] is not None:
                d[k] = str(d[k])
        d["started_at"] = self.started_at.isoformat()
        d["finished_at"] = self.finished_at.isoformat()
        return d
