"""Append-only JSONL provenance log."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ._base import AcquisitionResult

logger = logging.getLogger(__name__)

DEFAULT_PROVENANCE_PATH = Path("data/metadata/acquisition.jsonl")


def record(result: AcquisitionResult, path: Path | None = None) -> Path:
    """Append one ``AcquisitionResult`` as a JSON line.

    Returns the path written to. Creates parent directories as needed.
    """
    out = path or DEFAULT_PROVENANCE_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(result.to_jsonable(), ensure_ascii=False)
    with out.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    logger.debug("recorded provenance: %s", result.url)
    return out
