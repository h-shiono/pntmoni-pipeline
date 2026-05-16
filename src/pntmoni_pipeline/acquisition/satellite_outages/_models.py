"""Dataclasses for raw notices and normalised outage events.

Schema mirrors ``pntmoni-docs/40-data-schemas/satellite-outages.md``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class RawNotice:
    """One verbatim notice from an upstream channel.

    Persisted to ``raw_notices/{src}/{YYYY}/{YYYY-MM}.parquet``.
    """

    notice_id: str            # e.g. "NANU 2025001", "NAQU2025219", "NAGU 2026032"
    constellation: str        # "gps" | "gal" | "qzs"
    svn: int | None
    prn: int | None
    notice_type: str          # upstream-verbatim type label
    published_at: datetime    # UTC
    effective_at: datetime | None
    expires_at: datetime | None
    body_text: str            # full notice body, verbatim
    source_url: str
    fetched_at: datetime      # UTC
    source_sha256: str        # SHA-256 of body_text bytes
    extras: dict[str, Any] = field(default_factory=dict)  # constellation-specific metadata

    def to_jsonable(self) -> dict[str, Any]:
        d = asdict(self)
        d["published_at"] = self.published_at.isoformat()
        d["effective_at"] = self.effective_at.isoformat() if self.effective_at else None
        d["expires_at"] = self.expires_at.isoformat() if self.expires_at else None
        d["fetched_at"] = self.fetched_at.isoformat()
        return d


@dataclass(frozen=True)
class OutageEvent:
    """One normalised satellite-outage event spanning ≥1 raw notices.

    Persisted to ``events.parquet``.
    """

    event_id: str             # deterministic, e.g. "naqu:20250630:001"
    constellation: str        # "gps" | "gal" | "qzs"
    svn: int                  # primary identity (PRNs are recycled across SVNs)
    prn: int | None
    block: str | None         # satellite block / generation, when known
    start_at: datetime        # UTC
    end_at: datetime | None   # UTC; NULL = ongoing as of last_updated_at
    event_type: str           # enum: unscheduled_outage, scheduled_maintenance, decommissioning, health_change, frequency_outage, other
    severity: str             # enum: total, partial, informational
    affected_signals: list[str] | None  # NULL = "all signals on this SV"
    reason: str | None
    source_notice_ids: list[str]
    first_published_at: datetime
    last_updated_at: datetime
    is_active_at_publish: bool

    def to_jsonable(self) -> dict[str, Any]:
        d = asdict(self)
        d["start_at"] = self.start_at.isoformat()
        d["end_at"] = self.end_at.isoformat() if self.end_at else None
        d["first_published_at"] = self.first_published_at.isoformat()
        d["last_updated_at"] = self.last_updated_at.isoformat()
        return d
