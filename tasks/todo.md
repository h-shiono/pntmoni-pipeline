# Pipeline Tasks (Active)

This file tracks pipeline-specific sprint work. Cross-repository
tasks belong in `pntmoni-docs/tasks/cross-repo-todo.md`.

Format:

```markdown
## [YYYY-MM-DD] Task: <title>

### Goal
One sentence describing what this task accomplishes.

### Plan
- [ ] Step 1
- [ ] Step 2
- [ ] Step 3 (verification)

### Phase Guard
[ ] Confirmed this task is in Phase 0 scope
    (see pntmoni-pipeline/CLAUDE.md "Phase 0 Scope" section)

### Done Criteria
- Specific, observable outcome.

### Result
(Fill after completion)

### Open Issues
(Anything deferred)
```

---

## [2026-05-09] Task: Initial repository structure

### Goal
Establish the basic Python package structure for pntmoni-pipeline
matching the design in pntmoni-docs ADRs.

### Plan
- [x] Run `uv init --package pntmoni-pipeline --python 3.12`
- [x] Add CLASLIB as git submodule under `vendor/`
- [x] Create `reports/` Quarto project structure
- [x] Create `notebooks/` directory
- [x] Create `tasks/` directory and this `todo.md`
- [ ] Create `tasks/lessons.md`
- [ ] Add MRTKLIB as git submodule under `vendor/`
- [ ] Pin MRTKLIB to specific version (v0.6.3 or latest stable)
- [ ] Write minimal `README.md`
- [ ] Declare baseline dependencies in `pyproject.toml`

### Phase Guard
[x] Confirmed Phase 0 scope

### Done Criteria
- `uv sync` completes successfully
- Both submodules clone successfully on fresh checkout
- `quarto check` passes
- README.md provides setup instructions

### Open Issues
- Specific dependency selection: should be minimal at first;
  add as features are implemented (avoid premature dependency
  bloat)

---

## [2026-05-09] Task: Acquisition layer (GEONET / CDDIS / QZSS)

### Goal
Replace four legacy shell scripts (get_gsi_f5, get_gsi_rinex, get_brdc,
get_l6) with a Python acquisition layer that records provenance, supports
station filtering, and exposes a Typer CLI.

### Plan
- [x] Declare httpx, typer, pytest dependencies in pyproject.toml
- [x] `acquisition/_base.py`: AcquisitionResult, sha256_file, with_retry
- [x] `acquisition/_provenance.py`: JSONL append-log
- [x] `acquisition/_http.py`: streaming download + Earthdata auth resolver
- [x] `acquisition/_ftp.py`: GSI FTP list/download + station prefix filter
- [x] `acquisition/geonet_rinex.py`: GRJE_3.02 RINEX OBS, optional station filter
- [x] `acquisition/geonet_f5.py`: F5 yearly snapshot
- [x] `acquisition/cddis_brdc.py`: BRDC daily merged nav (Earthdata auth)
- [x] `acquisition/qzss_l6.py`: 24 hourly L6 files + concatenated AX
- [x] `cli/`: Typer app with `acquire {rinex,f5,brdc,l6}` subcommands
- [x] `configs/default.toml` baseline
- [x] Unit tests for hashing, provenance, URL composition (7 tests pass)
- [ ] Live integration test against a single GEONET station + DOY
      (requires GSI_FTP_USER/GSI_FTP_PASSWORD; defer until creds set)
- [ ] Live BRDC test against CDDIS (requires Earthdata Login)
- [ ] Live L6 test against QZSS public archive (no auth required)

### Phase Guard
[x] Confirmed Phase 0 scope (Initial GEONET acquisition module)

### Done Criteria
- All four sources have a Python implementation with parity to shell
- `pntmoni-pipeline acquire --help` lists rinex/f5/brdc/l6
- Provenance JSONL written to `data/metadata/acquisition.jsonl`
- Unit tests pass (`uv run pytest`)
- Live download produces a file whose SHA-256 matches a re-run

### Open Issues
- GEONET FTP NLST behaviour: server may return absolute or relative
  paths. Code handles both, but verify on first live run.
- License compliance: PDL 1.0 attribution applied at report-render
  time, not at acquisition time (internal use only here).
- Storage tiering: not implemented — `data/raw/` will grow until
  that lands. Track disk usage during first month of operation.

---

## [2026-05-09] Task: CLASLIB engine wrapper (rnx2rtkp)

### Goal
Provide a Python wrapper around CLASLIB's ``rnx2rtkp`` that consumes
the artefacts produced by the acquisition layer (no cold-storage copy
logic), runs one DOY across all GEONET stations in parallel up to
``cpu_count()``, and supports mode (config name) selection.

### Plan
- [x] Implement `src/pntmoni_pipeline/processing/`:
  - [x] `_base.py` — `ProcessingResult` dataclass
  - [x] `_obs_header.py` — RINEX header receiver/antenna parser
  - [x] `_config.py` — per-station config substitution + SHA-256 hash
  - [x] `_workspace.py` — workspace setup (binary/data/conf), gunzip
  - [x] `_binary.py` — rnx2rtkp locator + version detection
  - [x] `claslib_engine.py` — `process_station`, `process_doy`
- [x] CLI: `pntmoni-pipeline process claslib --date Y-M-D [--mode M] [-s ID] [-j N] [--force]`
- [x] Unit tests for header parsing, config substitution, gunzip,
      and path layout helpers (7 tests, all passing)
- [ ] Build rnx2rtkp binary: `make -C vendor/claslib/util/rnx2rtkp`
      (requires liblapack/libblas; manual step, not automated yet)
- [ ] Provide aux data files referenced by `kinematic_p30.conf` but
      not shipped with CLASLIB (`igs20.atx`, `clas_grid_003.def`)
      in a writable location (e.g. `configs/aux_data/`) and point
      `--data-dir` at it
- [ ] Live integration test for 2026-04-01 single-station first
      (requires above two manual steps)

### Phase Guard
[x] Confirmed Phase 0 scope (Initial CLASLIB processing module)

### Done Criteria
- All Python pieces implemented and unit-tested
- CLI exposes `pntmoni-pipeline process claslib`
- Engine version + per-station config SHA-256 captured in
  `ProcessingResult` (groundwork for the common Parquet schema)

### Open Issues
- L6 source: QZSS public archive (acquisition layer); local receiver
  integration deferred to Phase 1+
- Aux data files (`.atx`, `.def`, etc.) not yet inventoried — first
  live run will surface any missing references; document the
  resolution in `tasks/lessons.md`
- This task delivers the *wrapper*. The follow-on tasks are below.

---

## [Phase 0] Task: Common Parquet schema for processing output

### Goal
Convert CLASLIB ``.pos`` solution files into a Parquet schema shared
between CLASLIB and (future) MRTKLIB, with engine identification per
ADR 0001 / CLAUDE.md "Output schema".

### Plan
- [ ] Inventory `.pos` columns from a real run (CLASLIB Rev.L output)
- [ ] Define schema in `processing/_pos_to_parquet.py`:
      `processing_engine`, `engine_version`, `config_hash`,
      `station`, `epoch`, x/y/z (or lat/lon/h), Q (fix quality),
      ns (sat count), σ (covariance summary)
- [ ] Implement `pos_to_parquet(pos_path, engine, version, hash) -> Path`
- [ ] Wire into `process_doy` so processing also writes
      `data/processed/parquet/{mode}/{year}/{doy}/{station}.parquet`
- [ ] Round-trip test: read a sample `.pos` → Parquet → DataFrame
      with expected dtypes

### Phase Guard
[ ] Confirmed Phase 0 scope (output schema is part of the
    "First CLASLIB processing run" milestone)

### Done Criteria
- Sample `.pos` round-trips into Parquet without data loss
- Parquet file carries engine identification + config hash columns
- Downstream consumers can filter by engine/version/hash

---

## [Phase 0] Task: First Quarto report from sample data

### Goal
Render a minimal monthly report PDF using the existing Quarto
template and sample processed data.

### Plan
- [ ] Adapt `reports/templates/monthly.qmd` to consume Parquet via
  Python execution blocks
- [ ] Inject report metadata (period, version, methodology version)
- [ ] Render PDF and inspect visually
- [ ] Document reproduction steps in repository README
- [ ] CLI: `pntmoni-pipeline report monthly --month YYYY-MM`

### Phase Guard
[ ] Confirmed Phase 0 scope

### Done Criteria
- A PDF is produced under `reports/output/`
- The PDF contains: title, period, basic statistics, data
  provenance section
- Quarto rendering works reproducibly via CLI

### Open Issues
- Section coverage for Phase 0: keep minimal (Executive Summary,
  Performance Statistics, Data Provenance only). Full chapter
  set defined in `pntmoni-docs/10-product/03-monthly-report-spec.md`
  (when written).

---

## [2026-05-09] Task: Migrate to pntmoni-claslib fork

### Goal
Replace the upstream CLASLIB submodule reference with the
`pntmoni-claslib` fork created per ADR 0004, enabling TTFF
measurement on 30-second GEONET data.

This task depends on the fork repository being created and
MOD-001 (TTFF reset interval rounding) being implemented and
verified in the fork. See cross-repo todo:
`pntmoni-docs/tasks/cross-repo-todo.md`.

### Plan
- [ ] Wait for `pntmoni-claslib` fork to have at least one
      tagged release with MOD-001
- [ ] Update `.gitmodules`:
      - Remove `vendor/claslib` entry
      - Add `vendor/pntmoni-claslib` entry pointing to fork
- [ ] Run `git submodule sync && git submodule update --init`
- [ ] Update build instructions in CLAUDE.md and README.md
- [ ] Verify CLASLIB processing still works (existing behavior)
- [ ] Verify TTFF measurement now works on 30-second test data
- [ ] Update any internal path references in source code
      (`vendor/claslib/` → `vendor/pntmoni-claslib/`)
- [ ] Update lessons.md with any submodule migration gotchas

### Phase Guard
[ ] Confirmed Phase 0 scope (technical foundation, ADR 0004)

### Done Criteria
- `vendor/pntmoni-claslib/` is the active CLASLIB submodule
- Existing positioning processing is unchanged (same outputs)
- TTFF measurement works on 30-second sampled data
- Documentation references are updated

### Open Issues
- Fork repository must exist before this task can begin
- Verify build process changes (if any) between upstream
  CLASLIB and the fork

---

## How to use this file

When starting a task:
1. Add a new section using the template above
2. Confirm Phase Guard before implementing
3. Write the plan, get user approval, then implement
4. Mark `[x]` as steps complete

When finishing a task:
1. Fill in Result section with what changed and how verified
2. Note any followups in Open Issues
3. After ~2 months, move completed tasks to
   `tasks/archive/<YYYY-Q>.md` to keep this file lean
