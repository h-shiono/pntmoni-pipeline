"""Quality-control layer for PNT Moni pipeline.

Phase 0 ships :func:`teqc_for_doy` which produces teqc ``.{yy}S``
summary files from GEONET RINEX 3 inputs (via ``convbin`` v3→v2
conversion + Galileo/QZSS NAV header rewrites). The summary files
feed downstream QC scoring (qc_pass flag for the station registry —
see ``tasks/todo.md`` Backlog #2).
"""
from ._summary import QCSummaryResult, summarize_doy
from ._summary_parser import (
    ELEVATION_WINDOWS,
    MP_KEYS,
    SN_KEYS,
    StationQCSummary,
    parse_teqc_summary,
    to_wide_row,
    wide_columns,
)
from ._teqc import (
    DEFAULT_CONVBIN,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_RAW_RINEX_ROOT,
    DEFAULT_TEQC,
    DOYQCResult,
    StationQCResult,
    process_doy as teqc_for_doy,
    process_station as teqc_for_station,
)

__all__ = [
    "DEFAULT_CONVBIN",
    "DEFAULT_OUTPUT_ROOT",
    "DEFAULT_RAW_RINEX_ROOT",
    "DEFAULT_TEQC",
    "DOYQCResult",
    "ELEVATION_WINDOWS",
    "MP_KEYS",
    "QCSummaryResult",
    "SN_KEYS",
    "StationQCResult",
    "StationQCSummary",
    "parse_teqc_summary",
    "summarize_doy",
    "teqc_for_doy",
    "teqc_for_station",
    "to_wide_row",
    "wide_columns",
]
