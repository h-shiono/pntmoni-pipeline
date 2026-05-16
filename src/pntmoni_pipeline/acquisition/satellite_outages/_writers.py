"""Parquet writers for raw notices and normalised events.

Schema per ``pntmoni-docs/40-data-schemas/satellite-outages.md``.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ._models import OutageEvent, RawNotice

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"
METHODOLOGY_VERSION = "outage-norm-v1"


def _git_sha() -> str:
    import subprocess
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def write_raw_notices(
    raw_notices: list[RawNotice],
    *,
    dest_root: Path = Path("data/processed/satellite_outages/raw_notices"),
) -> dict[Path, int]:
    """Write raw notices grouped by ``(constellation, YYYY-MM)``.

    Returns a mapping of written path → row count.
    """
    grouped: dict[tuple[str, int, int], list[RawNotice]] = defaultdict(list)
    for n in raw_notices:
        key = (n.constellation, n.published_at.year, n.published_at.month)
        grouped[key].append(n)

    written: dict[Path, int] = {}
    for (const, yyyy, mm), members in grouped.items():
        dest = dest_root / const / f"{yyyy:04d}" / f"{yyyy:04d}-{mm:02d}.parquet"
        dest.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pylist([
            {
                "notice_id": n.notice_id,
                "constellation": n.constellation,
                "svn": n.svn,
                "prn": n.prn,
                "notice_type": n.notice_type,
                "published_at": n.published_at,
                "effective_at": n.effective_at,
                "expires_at": n.expires_at,
                "body_text": n.body_text,
                "source_url": n.source_url,
                "fetched_at": n.fetched_at,
                "source_sha256": n.source_sha256,
            }
            for n in members
        ])
        md = {
            b"schema_version": SCHEMA_VERSION.encode(),
            b"pipeline_git_sha": _git_sha().encode(),
            b"generated_at": datetime.now(UTC).isoformat().encode(),
            b"constellation": const.encode(),
            b"row_count": str(table.num_rows).encode(),
        }
        table = table.replace_schema_metadata(md)
        pq.write_table(table, dest)
        written[dest] = table.num_rows
        logger.info("wrote %s (%d rows)", dest, table.num_rows)
    return written


def write_events(
    events: list[OutageEvent],
    *,
    dest: Path = Path("data/processed/satellite_outages/events.parquet"),
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist([
        {
            "event_id": e.event_id,
            "constellation": e.constellation,
            "svn": e.svn,
            "prn": e.prn,
            "block": e.block,
            "start_at": e.start_at,
            "end_at": e.end_at,
            "event_type": e.event_type,
            "severity": e.severity,
            "affected_signals": e.affected_signals,
            "reason": e.reason,
            "source_notice_ids": e.source_notice_ids,
            "first_published_at": e.first_published_at,
            "last_updated_at": e.last_updated_at,
            "is_active_at_publish": e.is_active_at_publish,
        }
        for e in events
    ])
    md = {
        b"schema_version": SCHEMA_VERSION.encode(),
        b"methodology_version": METHODOLOGY_VERSION.encode(),
        b"pipeline_git_sha": _git_sha().encode(),
        b"generated_at": datetime.now(UTC).isoformat().encode(),
        b"n_events": str(table.num_rows).encode(),
    }
    table = table.replace_schema_metadata(md)
    pq.write_table(table, dest)
    logger.info("wrote %s (%d events)", dest, table.num_rows)
    return dest
