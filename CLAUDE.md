# CLAUDE.md — pntmoni-pipeline

## Project Context Loader (read first)

This is one of four repositories in the **PNT Moni** project. Before
making any architectural or strategic decisions, read these files in
the documentation repository:

1. `/Users/hayato/dev/pntmoni-docs/CLAUDE.md` — project overview,
   constraints, Phase 0 scope
2. `/Users/hayato/dev/pntmoni-docs/00-overview/04-current-status.md` —
   current state across all repositories

For pipeline-specific decisions, also consult:
- `/Users/hayato/dev/pntmoni-docs/30-evaluation-methodology/01-engine-strategy.md`
  (CLASLIB primary, MRTKLIB parallel evaluation)
- `/Users/hayato/dev/pntmoni-docs/70-decisions/adr-0001.md`
  (CLASLIB as Primary Processing Baseline)
- `/Users/hayato/dev/pntmoni-docs/70-decisions/adr-0002.md`
  (Four-Repository Structure)
- `/Users/hayato/dev/pntmoni-docs/70-decisions/adr-0004.md`
  (pntmoni-claslib Fork Strategy)
- `/Users/hayato/dev/pntmoni-docs/70-decisions/adr-0005.md`
  (TTFF Reset Period Selection)

### Repository Map
- `pntmoni-docs`: vision, strategy, ADRs, methodology
- **`pntmoni-pipeline` (this repo)**: local batch processing,
  Quarto report generation
- `pntmoni-cloud`: GCP infrastructure, Cloud Run APIs, Grafana
- `pntmoni-web`: Next.js frontend on Vercel (planned)

Strategic and cross-cutting concerns (business model, methodology,
ADRs) live exclusively in `pntmoni-docs`. Do not duplicate them here.

---

## Repository Purpose

`pntmoni-pipeline` is a Python package for local batch processing
that produces the analytical artifacts consumed by the rest of the
PNT Moni product family:

- Acquires GEONET observations, navigation data, IGS final SINEX,
  QZSS L6 archive
- Runs PPP-RTK processing through CLASLIB (primary) and MRTKLIB
  (parallel for cross-validation)
- Computes QC metrics (multipath via VIF method, observation
  continuity, coordinate stability)
- Performs statistical analysis (percentiles, regional, network
  topology, F10.7 correlations, integrity indicators)
- Generates monthly reports via Quarto (PDF + HTML)
- Uploads results (Parquet, PDFs) to GCS for `pntmoni-cloud`
  consumption

Heavy CPU work runs locally on the founder's workstation; the
output Parquet files become the canonical data source consumed by
the cloud-side API for dashboard and customer-facing displays.

---

## Setup

### Prerequisites
- Python 3.12 (managed via `uv`)
- Quarto CLI (https://quarto.org/) for report rendering
- Git with submodule support
- Local disk space (~500 GB recommended for RINEX archive)

### Initial setup

```bash
# Clone with submodules
git clone --recurse-submodules <repo-url>
cd pntmoni-pipeline

# Install Python environment
uv sync

# Verify CLASLIB engine submodule (fork — see ADR 0004)
ls vendor/pntmoni-claslib/

# Verify Quarto installation
quarto check
```

### CLASLIB engine: pntmoni-claslib fork

Per ADR 0004, this pipeline uses `pntmoni-claslib` (a transparent
fork of CLASLIB with documented modifications) rather than upstream
CLASLIB directly. The fork repository is at
`https://github.com/h-shiono/pntmoni-claslib` and is referenced
as a git submodule under `vendor/pntmoni-claslib/`.

The fork currently mirrors upstream verbatim and is tracked tag-for-tag.
PNT Moni-specific modifications follow the `MOD-NNN` protocol from
ADR 0004 and are documented in `vendor/pntmoni-claslib/PNTMONI_CHANGES.md`.
The first such modification (`MOD-001`: TTFF reset interval rounding for
sub-minute sampled data) is planned but not yet applied.

### MRTKLIB submodule (to be added)

```bash
git submodule add https://github.com/h-shiono/MRTKLIB vendor/mrtklib
cd vendor/mrtklib && git checkout v0.6.3
```

---

## Project Structure

```
pntmoni-pipeline/
├── pyproject.toml              # uv-managed, Python 3.12+
├── src/pntmoni_pipeline/       # Python package
│   ├── acquisition/            # Data fetchers (GEONET, IGS, L6)
│   ├── processing/             # CLASLIB and MRTKLIB engine wrappers
│   ├── qc/                     # QC metric computation
│   ├── analysis/               # Statistical analysis
│   ├── storage/                # Parquet, GCS, metadata
│   ├── reports/                # Quarto template binding
│   ├── orchestration/          # Workflow definitions
│   └── cli/                    # Typer-based CLI
├── reports/                    # Quarto project
│   ├── _quarto.yml
│   ├── _brand.yml
│   ├── styles/
│   ├── templates/
│   │   └── monthly.qmd
│   └── output/                 # Generated PDFs (gitignored)
├── notebooks/                  # Exploratory analysis
├── tasks/                      # todo.md, lessons.md
├── tests/
├── configs/                    # Runtime configurations
├── vendor/                     # Submodules
│   ├── claslib/                # Official QSS/CAO/MELCO implementation
│   └── mrtklib/                # Parallel validation engine (to add)
└── data/                       # Local data (gitignored)
    ├── raw/
    ├── processed/
    └── reports/
```

---

## Key Conventions

### Engine Strategy

This repository implements **dual-engine processing** per ADR 0001:

- **CLASLIB**: primary baseline for all monthly reports during
  2026–2027. Full evaluation across all GEONET stations.
- **MRTKLIB**: parallel evaluation on 100–200 sampled stations,
  used for cross-validation only. Becomes primary in 2027/Q4.

When implementing processing modules, both engines must be
supported behind a common interface (`processing/_base.py`).

### Configuration over code

Engine selection, station lists, and processing parameters are
controlled via TOML files in `configs/`, not by editing code:

- `configs/default.toml`: shared defaults
- `configs/monthly_report.toml`: full GEONET monthly run
- `configs/stations/parallel_sample.toml`: subset for MRTKLIB
  parallel evaluation

This enables Pro tier custom analyses (specific regions or stations)
without code changes.

### Output schema (Parquet)

Both engines write to a common Parquet schema with engine
identification:

```
processing_engine: "claslib" | "mrtklib"
engine_version: e.g., "Rev.L" | "0.6.3"
config_hash: SHA-256 of config TOML
```

This enables downstream consumers (cloud API, reports) to filter
by engine and verify reproducibility.

### Data provenance

Every data acquisition records metadata:
- Source (GEONET, IGS, NASA CDDIS, etc.)
- URL or identifier
- Retrieval timestamp
- SHA-256 hash of retrieved file
- File size

This metadata appears in monthly report's "Data Provenance"
section. Do not skip metadata recording even for "throwaway" runs.

### Report branding (ADR 0017)

Brand colors, typography, and the dual-palette discipline for the
Quarto reports are defined in **`pntmoni-docs`**, not here:

- Source of truth: `pntmoni-docs/60-brand/tokens.json` +
  `pntmoni-docs/70-decisions/adr-0017.md`
- `reports/styles/_pntmoni-tokens.scss` and
  `reports/templates/pntmoni-brand.typ` (future Typst PDF path) are
  **GENERATED** files vendored from pntmoni-docs. Never hand-edit
  them — regenerate with `node 60-brand/generate-tokens.mjs` in
  pntmoni-docs and re-vendor.
- HTML theme list: `[cosmo, styles/_pntmoni-tokens.scss,
  styles/pntmoni.scss]`; `pntmoni.scss` is the hand-maintained
  component layer on top of the tokens.
- Figures use the DATA palette only (chart primary `#2E6DA8`, status
  normal/degraded/critical `#2E8B6B`/`#E08A1E`/`#C24B3A`); brand gold
  `#E8C438` must NEVER appear in figure code. Documented exceptions:
  CLAS hex maps keep matplotlib `plasma`; QC figures keep the
  status-color interpolation (`CMAP_PERFORMANCE`).
- NO web-font embedding / `source: google` declarations in the report
  HTML (a past embed-resources build ballooned to 152 MB) — system
  fonts + fallback stacks only (see `reports/_brand.yml`).

### Storage tiering

RINEX OBS files do not stay in local hot storage indefinitely:

- **Tier 1 (Hot)**: Local disk, last 3 months
- **Tier 2 (Warm)**: GCS Standard, 4–12 months
- **Tier 3 (Cold)**: GCS Coldline/Archive, >1 year

Processing result Parquet files are kept indefinitely (smaller, more
valuable than re-downloadable RINEX).

---

## Workflow

### Plan Before Coding

For any task with 3+ steps or an architectural decision:
1. Write a plan to `tasks/todo.md` BEFORE touching code
2. Check Phase 0 scope (see `pntmoni-docs/CLAUDE.md`)
3. Check in with the user after planning
4. Mark `[x]` as you go

### Lessons

After every user correction, append to `tasks/lessons.md` using
the format established in `pntmoni-cloud/tasks/lessons.md`:

```markdown
## [YYYY-MM-DD] <category>: <short title>

**Mistake:** What went wrong.
**Root cause:** Why it happened.
**Fix applied:** What was done.
**Rule:** One-line rule to prevent recurrence.
**Tags:** #python #claslib #mrtklib #quarto #parquet #cost
```

If a lesson applies cross-repo (e.g., GCS interaction patterns
relevant to both pipeline and cloud), promote it to
`pntmoni-docs/50-operations/` and replace the local entry with a
brief reference.

### Verification Gate

Never mark a task complete without demonstrating correctness:
- Processing: show sample output (positioning solution, QC metrics)
  against known reference
- Reports: produce a sample Quarto PDF and inspect visually
- Tests: ensure relevant pytest tests pass

Ask: "Would a staff engineer approve this PR?"

### Cost Awareness

Local processing is "free" but watch for:
- Disk usage growth (set up storage tiering early)
- GCS upload costs for large Parquet files
- Cloud Run API costs when pipeline triggers cloud-side actions

Before adding any cloud resource, check
`pntmoni-cloud/CLAUDE.md` for cost discipline guidance.

### Elegance Check

Before presenting a non-trivial solution: "Is there a simpler way
that touches less code?" If the fix feels like a workaround,
implement the correct solution instead.

---

## CLI Conventions

The package exposes a single `pntmoni-pipeline` CLI script entry
point (configured in `pyproject.toml`). Commands are organized by
domain:

```
pntmoni-pipeline acquire ...     # data acquisition
pntmoni-pipeline process ...     # PPP-RTK processing
pntmoni-pipeline qc ...           # QC computation
pntmoni-pipeline analyze ...      # statistics
pntmoni-pipeline report ...       # Quarto report rendering
pntmoni-pipeline upload ...       # GCS sync
pntmoni-pipeline monthly ...      # full monthly workflow
```

Use Typer for CLI definition. Each subcommand should accept a
`--config` flag pointing to a TOML file in `configs/`.

---

## Phase 0 Scope (this repository)

### In scope (May–July 2026)

- Repository scaffolding (uv init, dependency declarations)
- CLASLIB submodule integration
- MRTKLIB submodule addition
- Initial GEONET acquisition module (single station test)
- Initial CLASLIB processing module (single day test)
- Initial Quarto template producing a usable PDF
- Storage layer for Parquet output
- Basic tests for acquisition and processing

### NOT in scope (defer to Phase 1+)

- Full 1300-station processing (Phase 1)
- Notice calendar scrapers (Phase 1, but may begin design)
- LLM-based report generation (Phase 1+)
- Pro tier custom report generation (Phase 3)
- Real-time L6 reception integration (Phase 1+)
- Cross-validation analysis automation (Phase 2)

When asked "should I implement X?", verify X is in Phase 0 scope.
If not, propose deferring rather than implementing.

---

## Open Questions

For repository-specific open questions, see `tasks/open-questions.md`
(when established).

For project-wide open questions, see
`pntmoni-docs/tasks/open-questions.md`.

---

## How to Resume Conversations

When starting a fresh Claude session about pipeline development:

> Read /Users/hayato/dev/pntmoni-pipeline/CLAUDE.md
> and the references it points to. Today I want to work on: <topic>

The CLAUDE.md chain (this file → pntmoni-docs/CLAUDE.md →
specific documents) gives Claude enough context to continue
without re-explaining the project.
