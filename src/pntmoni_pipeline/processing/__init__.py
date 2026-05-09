"""Processing layer for PNT Moni pipeline.

CLASLIB is the primary engine (ADR 0001). MRTKLIB will be added later
behind the same shape (``ProcessingResult``) for cross-validation.
"""
from ._base import ProcessingResult
from ._stats import RunSummary, format_summary

__all__ = ["ProcessingResult", "RunSummary", "format_summary"]
