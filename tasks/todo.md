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

## [Phase 0] Task: First GEONET acquisition module

### Goal
Implement minimal GEONET 30-second RINEX OBS acquisition for a
single station, with metadata recording.

### Plan
- [ ] Identify GEONET FTP/HTTP endpoint and access pattern
- [ ] Implement `src/pntmoni_pipeline/acquisition/geonet.py`
  - Function: `fetch_geonet_30s(date, station) -> Path`
  - Records metadata: source, URL, retrieval timestamp, SHA-256
- [ ] Store metadata in SQLite or JSONL `data/metadata/`
- [ ] Add basic test in `tests/unit/test_acquisition.py`
- [ ] CLI: `pntmoni-pipeline acquire geonet --date YYYY-MM-DD --station <id>`

### Phase Guard
[ ] Confirmed Phase 0 scope

### Done Criteria
- Successfully downloads RINEX OBS file for a chosen test station
  (e.g., 0231 — Tsukuba) for a recent date
- Metadata recorded and queryable
- Unit test passes

### Open Issues
- License compliance with GSI: confirm PDL 1.0 attribution applied
  to any redistributed data (this is internal use, not redistribution,
  but pattern should be established early)

---

## [Phase 0] Task: First CLASLIB processing run

### Goal
Run CLASLIB processing on the GEONET data acquired above and produce
a Parquet output with positioning solutions.

### Plan
- [ ] Build CLASLIB binaries from `vendor/claslib/`
- [ ] Implement `src/pntmoni_pipeline/processing/claslib_engine.py`
  - Wraps CLASLIB CLI invocation
  - Parses output to common schema
- [ ] Define common Parquet schema (see CLAUDE.md "Output schema")
- [ ] Write to `data/processed/parquet/`
- [ ] Add integration test on small sample data
- [ ] CLI: `pntmoni-pipeline process claslib --date YYYY-MM-DD --station <id>`

### Phase Guard
[ ] Confirmed Phase 0 scope

### Done Criteria
- CLASLIB processes the test station for a chosen date
- Output Parquet conforms to common schema
- Engine version, config hash recorded in output

### Open Issues
- L6 source: for first test, use QZSS public archive (not local
  receiver). Local receiver integration is Phase 1+.

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
