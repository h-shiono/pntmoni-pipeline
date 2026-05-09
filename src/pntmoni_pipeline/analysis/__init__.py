"""Statistical analysis layer for PNT Moni pipeline.

Currently houses TTFF (Time-To-First-Fix) extraction; will grow to
cover percentile error metrics, regional aggregates, F10.7
correlations, and integrity indicators per the planned layout in
``CLAUDE.md``.
"""
from ._reference_coords import (
    ComputeResult,
    FixedStationJump,
    compute_for_target,
    compute_for_targets,
    load_jumps,
)
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
    "ComputeResult",
    "FixedStationJump",
    "TTFFEvent",
    "TTFFSummary",
    "analyze_doy",
    "compute_for_target",
    "compute_for_targets",
    "extract_events",
    "format_summary",
    "load_jumps",
    "parse_pos_epochs",
    "parse_pos_quality",
    "summarize",
]
