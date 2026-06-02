"""Constellation-status snapshots from official GNSS operator pages.

Three scrapers (`gps.py`, `qzss.py`, `galileo.py`) fetch the respective
operator's public status page and return a common row schema; the
aggregator (`fetch_all`) concatenates them and writes a single
``constellation_status.parquet`` snapshot per fetch.

The monthly report reads the latest snapshot and renders per-satellite
status tables — the operator pages are themselves snapshots, not
period summaries, so the report's freshness equals the most recent
fetch time recorded in the ``fetched_at`` column.
"""
from __future__ import annotations

from ._aggregate import (  # noqa: F401
    RowSchema,
    fetch_all,
    fetch_galileo,
    fetch_gps,
    fetch_qzss,
    write_snapshot,
)
