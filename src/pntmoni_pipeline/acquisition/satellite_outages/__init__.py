"""Satellite outage notice acquisition (NANU / NAGU / NAQU).

This package fetches and parses per-constellation outage notices from
their upstream channels (USCG NAVCEN, GSC EUSPA, Cabinet Office Japan
via QSS), writes raw notices and normalised OutageEvents to Parquet,
and records provenance per the schema in
``pntmoni-docs/40-data-schemas/satellite-outages.md`` and the
data-flow ADR ``pntmoni-docs/70-decisions/adr-0012.md``.

Module layout:

- ``_models``: dataclasses for ``RawNotice`` and ``OutageEvent``
- ``_navstar_format``: shared parser for the NANU / NAQU
  "NOTICE ADVISORY TO ... USERS" body grammar (used for GPS + QZSS)
- ``nanu``, ``naqu``, ``nagu``: per-constellation fetchers
- ``events``: raw-notices → OutageEvent normalisation
- ``_provenance``: JSONL append helper at
  ``data/metadata/satellite_outages.jsonl``
"""
from . import nagu, nanu, naqu  # noqa: F401  (re-exports for CLI ergonomics)
from ._models import OutageEvent, RawNotice  # noqa: F401

__all__ = ["OutageEvent", "RawNotice", "nanu", "naqu", "nagu"]
