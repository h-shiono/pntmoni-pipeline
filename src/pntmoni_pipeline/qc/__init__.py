"""Quality-control layer for PNT Moni pipeline.

Phase 0 ships :func:`teqc_for_doy` which produces teqc ``.{yy}S``
summary files from GEONET RINEX 3 inputs (via ``convbin`` v3→v2
conversion + Galileo/QZSS NAV header rewrites). The summary files
feed downstream QC scoring (qc_pass flag for the station registry —
see ``tasks/todo.md`` Backlog #2).
"""
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
    "StationQCResult",
    "teqc_for_doy",
    "teqc_for_station",
]
