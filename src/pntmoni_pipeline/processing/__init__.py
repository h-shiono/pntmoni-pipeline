"""Processing layer for PNT Moni pipeline.

CLASLIB is the primary engine (ADR 0001). MRTKLIB will be added later
behind the same shape (``ProcessingResult``) for cross-validation.
"""
from ._base import ProcessingResult

__all__ = ["ProcessingResult"]
