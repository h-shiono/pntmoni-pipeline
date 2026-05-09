"""Data acquisition layer for PNT Moni pipeline.

Modules expose a uniform pattern: each ``fetch(...)`` call returns one or
more :class:`AcquisitionResult` records, appended to the JSONL provenance
log at ``data/metadata/acquisition.jsonl``.
"""
from ._base import AcquisitionResult, sha256_file
from ._provenance import record as record_provenance

__all__ = [
    "AcquisitionResult",
    "record_provenance",
    "sha256_file",
]
