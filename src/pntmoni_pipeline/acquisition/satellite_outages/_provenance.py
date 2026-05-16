"""Provenance JSONL for satellite-outage acquisition runs."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PROVENANCE_PATH = Path("data/metadata/satellite_outages.jsonl")


def record(
    constellation: str,
    source_url: str,
    *,
    n_notices: int,
    raw_parquet: Path | None,
    events_parquet: Path | None,
    extras: dict[str, Any] | None = None,
    path: Path | None = None,
) -> Path:
    out = path or DEFAULT_PROVENANCE_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "constellation": constellation,
        "source_url": source_url,
        "n_notices": n_notices,
        "raw_parquet": str(raw_parquet) if raw_parquet else None,
        "events_parquet": str(events_parquet) if events_parquet else None,
        "extras": extras or {},
        "generated_at": datetime.now(UTC).isoformat(),
    }
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    logger.debug("recorded satellite_outages provenance: %s n=%d", constellation, n_notices)
    return out
