"""Acquisition primitives: result dataclass, hashing, retry."""
from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class AcquisitionResult:
    """Provenance record for one acquired file.

    Persisted to ``data/metadata/acquisition.jsonl`` so monthly reports
    can render a Data Provenance section per project conventions.
    """

    source: str
    url: str
    path: Path
    sha256: str
    size_bytes: int
    retrieved_at: datetime
    skipped: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_jsonable(self) -> dict[str, Any]:
        d = asdict(self)
        d["path"] = str(self.path)
        d["retrieved_at"] = self.retrieved_at.isoformat()
        return d


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def utcnow() -> datetime:
    return datetime.now(UTC)


def with_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    initial_backoff: float = 2.0,
    max_backoff: float = 30.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    label: str = "operation",
) -> T:
    """Run ``fn`` with exponential backoff. Re-raises the last exception."""
    backoff = initial_backoff
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except retry_on as exc:
            last_exc = exc
            if attempt == attempts:
                break
            logger.warning(
                "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                label, attempt, attempts, exc, backoff,
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
    assert last_exc is not None
    raise last_exc
