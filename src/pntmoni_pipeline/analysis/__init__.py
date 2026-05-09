"""Statistical analysis layer for PNT Moni pipeline.

Currently houses TTFF (Time-To-First-Fix) extraction; will grow to
cover percentile error metrics, regional aggregates, F10.7
correlations, and integrity indicators per the planned layout in
``CLAUDE.md``.
"""
from ._epoch_errors import (
    DAY_HOURS_UTC,
    EpochErrorsResult,
    compute_epoch_errors,
    parse_pos_nmea,
)
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
    "DAY_HOURS_UTC",
    "EpochErrorsResult",
    "FixedStationJump",
    "TTFFEvent",
    "TTFFSummary",
    "analyze_doy",
    "compute_epoch_errors",
    "compute_for_target",
    "compute_for_targets",
    "extract_events",
    "format_summary",
    "load_jumps",
    "parse_pos_epochs",
    "parse_pos_nmea",
    "parse_pos_quality",
    "summarize",
]
