# pntmoni-pipeline

Local batch processing pipeline for **PNT Moni** — an independent
evaluation service for satellite navigation augmentation systems
(QZSS CLAS, MADOCA-PPP, future Galileo HAS, BeiDou PPP-B2b).

This repository acquires GEONET observations and reference data,
runs PPP-RTK processing through CLASLIB and MRTKLIB, computes
quality metrics, and generates Quarto-based monthly reports.

For project-wide context, see the documentation repository:
[pntmoni-docs](https://github.com/h-shiono/pntmoni-docs) (private).

## Status

Phase 0 (May–July 2026): foundational scaffolding in progress.

## Quick Start

### Prerequisites

- Python 3.12 or later (managed via `uv`)
- [Quarto CLI](https://quarto.org/) for report rendering
- Git with submodule support

### Setup

```bash
# Clone with submodules
git clone --recurse-submodules <repo-url>
cd pntmoni-pipeline

# Install Python environment
uv sync

# Verify submodules
ls vendor/pntmoni-claslib/    # CLASLIB engine (transparent fork — see ADR 0004)
ls vendor/mrtklib/            # MRTKLIB submodule (to be added)

# Verify Quarto installation
quarto check
```

### Build Processing Engines

The CLASLIB engine (via `pntmoni-claslib` fork — see ADR 0004) and
MRTKLIB are included as git submodules and must be built before
processing can run.

```bash
# CLASLIB engine (pntmoni-claslib fork)
make -C vendor/pntmoni-claslib/util/rnx2rtkp
# Requires liblapack and libblas to be installed (Linux: apt install
# liblapack-dev libblas-dev; macOS: brew install lapack openblas).

# MRTKLIB (when added)
# Build instructions per MRTKLIB README
```

Modifications to the CLASLIB fork are documented in
`vendor/pntmoni-claslib/PNTMONI_CHANGES.md` per the protocol in
ADR 0004.

## Repository Structure

```
src/pntmoni_pipeline/   # Python package
reports/                 # Quarto project (templates, styles)
notebooks/               # Exploratory analysis
tasks/                   # todo.md, lessons.md
vendor/                  # Submodules
  pntmoni-claslib/       # CLASLIB engine (transparent fork; ADR 0004)
  mrtklib/               # Parallel validation engine (planned)
```

For full structure and conventions, see `CLAUDE.md`.

## Engine Strategy

This pipeline runs **dual-engine processing** during 2026–2027:

- **CLASLIB** (primary): used for all monthly reports and full
  GEONET evaluation
- **MRTKLIB** (parallel): used for cross-validation on a sampled
  subset (100–200 stations)

The primary baseline transitions to MRTKLIB in 2027/Q4. See
[ADR 0001](https://github.com/h-shiono/pntmoni-docs/blob/main/70-decisions/adr-0001.md)
for rationale.

## License & Attribution

This pipeline uses several upstream resources:

- **GEONET data**: provided by the Geospatial Information Authority
  of Japan (GSI), used under the Public Data License 1.0 (PDL 1.0)
  with attribution.
- **CLASLIB**: BSD 2-Clause license with explicit commercial use
  permission. Copyright (c) 2007-, T. Takasu; (c) 2014-, GSI;
  (c) 2017-, Mitsubishi Electric Corp. PNT Moni runs CLASLIB via
  the transparent fork `pntmoni-claslib` (see ADR 0004); the fork
  inherits the same BSD 2-Clause license and documents every
  modification in `PNTMONI_CHANGES.md`.
- **MRTKLIB**: Open-source modernized fork of RTKLIB.

Output reports include full data provenance and acknowledgements.

## Documentation

- Project context: `CLAUDE.md` (this repository)
- Strategic and architectural documentation: pntmoni-docs
  - Engine strategy: `30-evaluation-methodology/01-engine-strategy.md`
  - Repository structure: `70-decisions/adr-0002.md`
  - Current status: `00-overview/04-current-status.md`

## Development

Active sprint work is tracked in `tasks/todo.md`.
Lessons learned are accumulated in `tasks/lessons.md`.

For pipeline development conventions, including the engine wrapper
interface and the common Parquet output schema, see `CLAUDE.md`.
