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

## [2026-05-09] Task: Processing run-time statistics (Tier 1+2)

### Goal
Capture per-DOY processing wall time + per-station duration
distribution so we know how long a 1300-station monthly batch
will take and can detect silent regressions after CLASLIB fork
rebases or `MOD-NNN` modifications.

### Plan
- [x] `processing/_stats.py`: `RunSummary` dataclass, `summarize`,
      `record` (JSONL append), `format_summary`, `percentile`
- [x] `process_doy` tracks failed stations, builds `RunSummary` at
      end, logs the formatted summary (Tier 1) and appends one
      JSONL line to `data/metadata/processing.jsonl` (Tier 2)
- [x] `process_doy` return signature now `(results, summary)`;
      CLI prints summary to stdout
- [x] Unit tests: percentile edge cases, summarize counts,
      JSONL append, format_summary truncation (8 tests)
- [ ] After first live DOY run, capture median per-station duration
      and document in `tasks/lessons.md` so monthly-batch budget
      is visible from session start

### Phase Guard
[x] Confirmed Phase 0 scope (operational visibility for Phase 0
    "First CLASLIB processing run" milestone)

### Done Criteria
- A live `process claslib` run prints wall time, p50/p95/total
  duration, succeeded/skipped/failed counts
- `data/metadata/processing.jsonl` accumulates one record per run
  for trend tracking
- 22/22 unit tests pass

### Open Issues
- A future small `process stats` CLI subcommand could read the
  JSONL and print historical trends — defer until ≥2 months of
  records exist (don't build the read side prematurely)

---

## [2026-05-09] Task: TTFF analyzer (15-min primary, ADR 0005)

### Goal
Extract Time-To-First-Fix per reset window from CLASLIB ``.pos``
output produced with ``misc-regularly = 900`` (Phase 0 primary period).
Persist per-station summaries to ``data/metadata/ttff.jsonl`` for
trend tracking.

### Plan
- [x] `configs/kinematic_p30_ttff_verify.conf` (TTFF + verify aux data)
- [x] `analysis/_ttff.py`:
  - [x] `parse_pos_epochs` — UTC→GPST→`epoch_idx_of_day` map
        (gap-tolerant)
  - [x] `extract_events` — per reset window first-Q=4 detection
  - [x] `summarize` — fix success rate, p50/p95/min/max TTFF
  - [x] `record` — JSONL append
  - [x] `analyze_doy` — auto-detect `misc-regularly` from per-station
        config; full-DOY walk
- [x] `cli/analyze.py`: `pntmoni-pipeline analyze ttff` subcommand
- [x] Unit tests for percentile, summarize, JSONL, gap-handling
      (10 tests, all passing — 34/34 total)
- [x] Live verified: DOY 091 / 1298 stations / 124,608 TTFF samples
  - Wall-time impact vs non-TTFF: within noise (< 2%)
  - Median per-station p50: **180 s**
  - Median per-station p95: **300 s**
  - Mean fix-success-rate: 94.26% raw / 94.40% excluding 0-fix outliers
- [x] Bug fix: alignment by line index broke on stations with
      observation gaps (e.g. 0085, 0454) — now aligned via GPST TOW
      so window boundaries match CLASLIB MOD-001's TOW-modulo reset

### Phase Guard
[x] Confirmed Phase 0 scope (ADR 0005 primary period)

### Done Criteria
- [x] `pntmoni-pipeline analyze ttff` produces sensible per-station
  TTFF summaries with no zero-percentile artefacts on gap-affected
  stations
- [x] `data/metadata/ttff.jsonl` accumulates one record per
  (station, date, mode) for trend tracking
- [x] 34/34 unit tests pass

### Open Issues / next
- 60-min secondary period (ADR 0005) is Phase 1 work; no design
  blocker — same `--reset-period 3600 --mode kinematic_p30_ttff_h1`
  pattern. Pending fork-side hourly mode config.

---

## [2026-05-09] Task: Reference coordinates from F5 (15-day median, CMR)

### Goal
Build per-station truth coordinates from GSI's F5 archive so we can
compute horizontal/vertical error percentiles (95th, 99th, 99.9th)
of CLASLIB epoch solutions vs the truth. Each (target_date, station)
pair gets one (X, Y, Z) ECEF row.

### Plan
- [x] `analysis/_f5_reader.py` — parse F5 ``.pos`` (header 20 + footer 2,
  metadata + daily series + sha256)
- [x] `analysis/_reference_coords.py` —
  - load fixed-station window across target±7d
  - apply jumps from `configs/gsi_jumps.toml` (fixed station only)
  - per-day common-mode removal: `relative_i = station_i − fixed_i`
  - `station_truth = nanmedian(relative) + nanmedian(fixed_with_jumps_NaNed)`
  - multi-target driver (week / month support)
- [x] `configs/gsi_jumps.toml` — curated schema, initially empty
- [x] CLI: `pntmoni-pipeline analyze reference-coords {--date|--week}`
- [x] Output: Parquet at
  `data/processed/reference_coords/{year}/{YYYYMMDD|Wnn}.parquet`
- [x] Provenance JSONL: per-target record of fixed station, jumps
  applied, F5 sha256 per file, n_days_used, etc.
- [x] Unit tests: F5 metadata, CMR truth recovery, jump-only-on-fixed,
  too-few-days error, TOML loading, multi-day driver (7/7 passing)
- [x] Live verified for 2026-03-15: 1302 stations, 117 KB Parquet,
  Tsukuba1 day-to-day stability sub-mm, 2.45 s wall
- [x] Live verified for 2026-W11 (7-day batch): 9114 rows, 399 KB
  Parquet, 15 s wall

### Phase Guard
[x] Confirmed Phase 0 scope (truth coords are foundational for
    percentile error metrics in monthly reports — CLAUDE.md
    "Performs statistical analysis (percentiles, ...)")

### Done Criteria
- [x] `analyze reference-coords` produces Parquet for either
  --date or --week
- [x] Method B (per-day CMR) implemented and tested against synthetic
  jump scenarios — recovers truth exactly when CMR cancels drift
- [x] Provenance JSONL accumulates one record per target-date

### Open Issues / next
- Acquire 2025 F5 archive when targets near Jan/Feb need cross-year
  windows
- Curated `configs/gsi_jumps.toml` is empty; populate as needed by
  watching https://terras.gsi.go.jp/information.php
- A future `pntmoni-pipeline acquire gsi-jumps` could scrape the
  page and propose TOML diffs, keeping scrape out of the critical path

---

## [Phase 0–1] Task: Station qualification + dual-aggregate

### Goal
Establish the analysis-layer mechanism that decides which GEONET
stations qualify as "CLAS evaluation reference" stations, applying
observation-quality criteria at aggregation time (not by hardcoded
exclusion at processing). Produce two parallel aggregate metrics
in monthly reports: raw across all 1298 stations, and qualified
subset across stations meeting the criteria.

### Motivation
- 1098 (南鳥島) and 1140 (沖ノ鳥島) report 100% Q=1 because they are
  outside CLAS coverage. They drag the global FIX rate down by a
  small but methodologically meaningful amount.
- The previous toolbox handled this by qualifying stations at the
  aggregation stage based on observation quality. PNT Moni inherits
  that approach — see lessons.md "CLAS evaluation qualification belongs
  at aggregation, not processing".
- The same mechanism becomes the basis for monthly report's
  methodology section: "evaluated against N stations meeting criteria
  X, Y, Z".

### Plan (sketch — refine when picked up)
- [ ] Define qualification criteria. Candidates:
  - Observation completeness (e.g. ≥95% of expected epochs present —
    `n_observed_epochs / 2880` for 30s daily)
  - SNR / multipath quality (VIF method, planned `qc/` module)
  - F5 coordinate stability (use the F5 archive we already acquire)
  - CLAS coverage check (any matching `inet=N` from trace) — implicit
    via fix-rate threshold
- [ ] Persist per-station QC metrics alongside TTFF (e.g.
  `data/metadata/qc.jsonl`)
- [ ] Implement `analysis/qualification.py` that joins QC + coverage
  + criteria into a `qualified: bool` flag per (station, date)
- [ ] Update aggregate scripts to report dual metrics (raw + qualified)
- [ ] Document the criteria in
  `pntmoni-docs/30-evaluation-methodology/` (or write the methodology
  doc if not yet present)

### Phase Guard
[ ] Phase 0–1 (begins once monthly report scaffolding lands; the
    aggregate output schema feeds report templates)

### Done Criteria
- A single station can be flagged qualified or not based on a TOML
  criteria file
- Monthly report shows BOTH raw N=1298 and qualified subset metrics
- Criteria are auditable and reproducible from raw .pos + provenance

### Open Issues
- Specific thresholds (95% completeness? 90%?) need to be empirically
  set after a few months of trend data
- "Qualified" definition may evolve — tie versioning to the
  methodology doc to keep cross-report comparability

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
`pntmoni-claslib` fork created per ADR 0004, establishing the
foundation for TTFF measurement on 30-second GEONET data via
the planned `MOD-001` modification.

### Plan
- [x] `pntmoni-claslib` fork repository created at
      `https://github.com/h-shiono/pntmoni-claslib` (currently a
      verbatim mirror of upstream; `MOD-001` to be applied later)
- [x] Update `.gitmodules`:
      - Remove `vendor/claslib` entry
      - Add `vendor/pntmoni-claslib` entry pointing to fork
- [x] Deinit + remove old submodule, register new submodule
      (`git submodule add ... vendor/pntmoni-claslib`)
- [x] Update build instructions in CLAUDE.md and README.md
- [x] Update internal path references in source code:
      - `processing/_binary.py` default search order
      - `processing/claslib_engine.py` default `data_dir`
      - `cli/process.py` default `--data-dir`
- [x] Tests pass against new layout (14/14)
- [ ] Apply `MOD-001` (TTFF reset interval rounding) to the fork
      and tag a release (separate task, blocked on fork-side work)
- [ ] Verify CLASLIB processing still produces identical
      positioning solutions as upstream (1-second test data)
- [ ] Verify TTFF measurement triggers at expected reset
      boundaries on 30-second test data once MOD-001 is applied
- [ ] Update lessons.md with any submodule migration gotchas

### Phase Guard
[x] Confirmed Phase 0 scope (technical foundation, ADR 0004)

### Done Criteria
- [x] `vendor/pntmoni-claslib/` is the active engine submodule
- [x] Documentation references updated; pipeline tests still pass
- [ ] Existing positioning processing produces same outputs
      as upstream (verified after first live integration run)
- [ ] TTFF measurement works on 30-second sampled data (after
      MOD-001 lands)

### Open Issues
- MOD-001 implementation is the next step (separate fork-side
  task tracked in `pntmoni-docs/tasks/cross-repo-todo.md`)
- Aux data files referenced by `kinematic_p30.conf` not shipped
  with CLASLIB (`igs20.atx`, `clas_grid_003.def`) — to be staged
  in `configs/aux_data/` or similar before first live run

### Result
- Submodule swap completed 2026-05-09. `vendor/claslib` removed
  cleanly via `git submodule deinit + git rm + rm .git/modules/...`;
  `vendor/pntmoni-claslib` registered via `git submodule add`. Fork
  HEAD = `23cfd363` (same as upstream — verbatim mirror with tag
  `082` ahead). All path-reference updates concentrated in 5 files
  (`_binary.py`, `claslib_engine.py`, `process.py`, `CLAUDE.md`,
  `README.md`); 14 unit tests still pass. The `vendor/claslib`
  fallback in `_binary._DEFAULT_LOCATIONS` is retained for
  environments still on the pre-fork layout.

---

# Backlog (2026-05-09 — added per user direction)

The tasks below are stacked for future sprints. They share dependencies
and will likely be picked up alongside the monthly-report scaffolding.
Order is rough — the accuracy chain (4) and station registry (1) are
prerequisites for (5) and (6); QC framework (2) feeds qualification.

---

## [Phase 0–1] Task: GEONET station registry with metadata

### Goal
Maintain a curated registry of every GEONET station's metadata so the
analysis layer can join CLASLIB output against network membership,
official-evaluation flags, QC pass/fail, and coverage flags.

### Plan
- [x] Layered TOML source files under `configs/stations/`:
  - `network_assignments.toml` — netid + isinside (slow-changing)
  - `network_info.toml` — top-4 CLAS grid weights per station (from
    CLASLIB debug trace)
  - `eval_periods.toml` — per-station list of eval-point validity
    periods (multi-period supported per fiscal half / earthquake
    recovery scenarios)
- [x] `scripts/migrate_legacy_station_data.py` — one-shot migration
  from `gnss_research_toolbox/clas_eval/`. Reads station_ng.csv (5
  years), station_network_info.csv (latest), and
  service_performance/fy*_*_h.csv (9 files spanning 2020-Q4 →
  2024-Q4). Provenance header in each TOML records source paths +
  legacy git SHA.
- [ ] Identity layer: derive `data/processed/stations/identity.parquet`
  from F5 SITE/INF (auto, year-round refresh)
- [ ] `analysis/registry.py` — runtime loader that joins all layers
  and resolves `is_eval` for a target date by walking each station's
  periods. Returns one DataFrame for the qualification step.
- [ ] Acquisition / analysis / report layers consume the joined view

### Phase Guard
[x] Phase 0–1

### Done Criteria
- [x] 3 TOML files generated, parse cleanly with `tomllib`
- [x] eval_periods captures the multi-period audit cases
  (e.g. 0618, 0810, 0969 — eval, dropped, briefly restored, dropped)
- [ ] `registry.load(target_date)` returns a unified DataFrame
- [ ] Qualification + dual-aggregate joins on this registry

### Open Issues
- Source of "CLAS Official evaluation point" flag — `pntmoni-docs`
  references the legacy repo for traceability; future updates land in
  the TOML directly (not from an automated source)
- 29 eval-stations are flagged `isinside=False` in 2025 station_ng;
  treat eval_periods as authoritative and isinside as a secondary
  signal in the qualification logic (see lessons.md audit note)
- Network membership at coverage edges may be ambiguous; preserve
  both `netid` and `isinside` so the qualification step can pick

---

## [Phase 0–1] Task: QC framework for station observation quality

### Goal
Per-station QC pass/fail flag computed from observation-quality
metrics (multipath / VIF, SNR, data completeness, …). Output feeds
the station registry's `qc_pass` field and the qualification mechanism.

### Plan
- [ ] Receive QC reference script from user (pending)
- [ ] Adapt to PNT Moni layout: read RINEX OBS / .pos, write per-station
  QC summary to `data/processed/qc/{date}.parquet`
- [ ] Define qc_pass criteria thresholds (TBD; likely empirical after
  a few months of trend data)
- [ ] Provenance JSONL at `data/metadata/qc.jsonl`

### Phase Guard
[ ] Phase 0–1

### Open Issues
- Awaiting user's reference QC script
- Confirm VIF (Variance Inflation Factor) definition matches CLAS
  Official methodology

---

## [Phase 1+] Task: TTFF — per-network reset timing semantics

### Goal
The current TTFF analyzer assumes a single uniform reset period
(`misc-regularly = 900` for CLAS). When evaluation extends beyond
CLAS — to MADOCA-PPP, Galileo HAS, BeiDou PPP-B2b, etc. — data
delivery cadence differs and reset semantics must reflect that.

### Plan (sketch)
- [ ] Document each evaluated network's data-delivery cadence
- [ ] Per-network mode configs select an appropriate `misc-regularly`
  and per-message-rate processing options
- [ ] Generalise `extract_events` to accept an explicit reset schedule
  (not only a uniform period) so non-uniform-reset networks fit the
  same analyser
- [ ] Per-network TTFF interpretation enters the monthly report's
  methodology section

### Phase Guard
[ ] Phase 1+ (initial Phase 0 is CLAS-only)

### Open Issues
- Galileo HAS reset cadence: TBD
- MADOCA-PPP: 60 s message rate but slower convergence → reset
  semantics need a separate methodology discussion before fixing

---

## [Phase 0] Task: Accuracy pipeline `.pos` → ENU → percentiles → DB schema

### Goal
Convert per-epoch CLASLIB ``.pos`` solutions into horizontal/vertical
positioning errors (ENU relative to reference truth), aggregate into
per-station percentiles (50, 95, 99, 99.9), and stage in a schema
suitable for `pntmoni-cloud` ingestion. This is the core data flow for
monthly reports.

### Background
The reference toolbox followed a two-stage chain:
1. ``.pos`` × smoothed F5 truth → per-epoch ENU error CSV (intermediate)
2. per-station percentile CSV across all stations
This task aligns our pipeline on the same chain, picks intermediate
formats (Parquet vs CSV), and defines the DB schema for cloud ingestion.

### Plan (sketch)
- [ ] **Stage 1: per-epoch ENU errors**
  - Read `.pos` ($GPGGA → time, lat, lon, h, q, n_sats)
  - Read reference coord for (date, station) from
    `data/processed/reference_coords/{year}/...parquet`
  - Compute ENU (geodetic → ECEF → ECEF-difference → ENU at ref)
  - Output: `data/processed/epoch_errors/{mode}/{year}/{doy}/{station}.parquet`
    columns: `epoch_idx`, `tow`, `q`, `n_used_sats`, `n_obs_sats`,
    `e_m`, `n_m`, `u_m`, `horizontal_m`, `is_day` (see day/night task)
- [ ] **Stage 2: per-station percentile aggregate**
  - From all epoch_errors of a DOY → per-station percentiles
    (50/95/99/99.9) for horizontal + vertical
  - Output: `data/processed/accuracy/{mode}/{year}/{month}.parquet`
    columns: `date`, `station`, `mode`, `engine_version`, `n_epochs`,
    `n_used_q4`, `q4_rate`, `h_p50`, `h_p95`, `h_p99`, `h_p999`,
    `v_p50`, `v_p95`, `v_p99`, `v_p999`,
    `h_p95_day`, `h_p95_night`, … (day/night task)
    `n_obs_p50`, `n_used_p50`, `used_obs_ratio_p50`, … (sat-count task)
- [ ] **DB schema**: this Stage 2 Parquet IS the schema; document it
  for `pntmoni-cloud` ingestion (BigQuery external table or load-job)

### Phase Guard
[ ] Phase 0 (foundational for monthly report)

### Done Criteria
- Sample DOY: `.pos` → epoch_errors Parquet → accuracy Parquet
  round-trip works end-to-end
- Schema reviewed and signed off for cloud ingestion (cross-repo
  alignment with `pntmoni-cloud`)
- Numbers reproducible from raw `.pos` + reference_coords + provenance

### Open Issues
- ENU coordinate definition: use F5 reference lat/lon (we have it)
  vs station's RINEX header reference position. Lean: F5 (consistent
  across stations).
- epoch_errors volume: NMEA cadence × 1300 stations × 30 days
  ≈ 100M rows/month. Keep as gzip-Parquet vs treat as
  recompute-on-demand intermediate? Lean: keep — small, joinable.
- Cloud-side schema: Parquet on GCS + DuckDB + Cloud Run (per
  pntmoni-cloud/CLAUDE.md GCS Parquet rationale)

---

## [Phase 0] Task: Day/Night split accuracy metrics

### Goal
Per-station percentile errors computed for daytime and nighttime
separately, so monthly reports can show the ionospheric influence on
PPP-RTK accuracy.

### Plan (sketch)
- [ ] Define day/night cutoff per epoch:
  - Default proposal: solar zenith angle threshold (e.g. zenith ≤ 90°
    = day) computed from station lat/lon + epoch UTC. Station-specific
    so it stays accurate across seasons and at high latitudes.
  - Simpler alternative: fixed UTC criterion (e.g. 21:00–09:00 UTC =
    night for Japan stations); inferior near solstices but
    requires no additional computation.
- [ ] Tag each row in Stage 1 (epoch_errors) with `is_day: bool`
- [ ] Stage 2 computes percentiles separately for day-epochs and
  night-epochs; output gains `h_p95_day`, `h_p95_night`, etc.
- [ ] Monthly report shows side-by-side day/night

### Phase Guard
[ ] Phase 0

### Open Issues
- Solar zenith vs UTC vs civil twilight: pick one, record in
  methodology, do not switch silently between reports

---

## [Phase 0] Task: Satellite count metrics (observed vs used)

### Goal
Per-epoch and per-station satellite-count distributions: how many
satellites were observed, how many were actually used in the
positioning solution, and the used/observed ratio. Tracks how
aggressively the engine rejects sats (multipath, mask, healthy/
unhealthy) and is a leading indicator of degraded conditions.

### Background
- **Used count** is in NMEA `$GPGGA` field 8 (already in our `.pos`
  output)
- **Observed count** requires either RINEX OBS header / per-epoch
  scan, or the CLASLIB `.pos.trace` per-epoch listing
- Ratio `used / observed` ≪ 1 indicates strong rejection (likely
  obstruction or multipath); ≈ 1 indicates clean conditions

### Plan (sketch)
- [ ] Stage 1 (epoch_errors): record `n_obs_sats` and `n_used_sats`
  per epoch (from RINEX scan or trace + NMEA)
- [ ] Stage 2 (accuracy): aggregate distribution stats — `n_obs_p50`,
  `n_used_p50`, `used_obs_ratio_p50`, `_p95`, etc.
- [ ] Constellation breakdown (G/R/E/J/C) where the source supports it
- [ ] Monthly report shows distributions + per-network comparison

### Phase Guard
[ ] Phase 0

### Open Issues
- Observed-count source: trace file is cheap (no re-reading RINEX)
  but needs verification that it counts ALL observed sats (not only
  CLAS-eligible). If trace is incomplete, fall back to RINEX scan.
- Constellation breakdown: NMEA only gives a single count; we may
  need RINEX or additional CLASLIB output to split by constellation.

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
