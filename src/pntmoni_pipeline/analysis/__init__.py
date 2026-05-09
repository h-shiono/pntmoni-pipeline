"""Statistical analysis layer for PNT Moni pipeline.

Currently houses TTFF (Time-To-First-Fix) extraction; will grow to
cover percentile error metrics, regional aggregates, F10.7
correlations, and integrity indicators per the planned layout in
``CLAUDE.md``.
"""
from ._ttff import (
    TTFFEvent,
    TTFFSummary,
    analyze_doy,
    extract_events,
    format_summary,
    parse_pos_epochs,
    parse_pos_quality,
    summarize,
)

__all__ = [
    "TTFFEvent",
    "TTFFSummary",
    "analyze_doy",
    "extract_events",
    "format_summary",
    "parse_pos_epochs",
    "parse_pos_quality",
    "summarize",
]
