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

## [2026-06-10] Task: Bilingual (JA/EN) report templates

### Goal
Make each Quarto report template render in both Japanese and English
from a single source, with no duplication of the Python compute/plot
code (which is the drift-prone part). monthly_qc first as the
reference pattern, then monthly_free.

### Design (validated empirically — Quarto 1.9.37)
Single switch: `quarto render <tmpl>.qmd --profile {ja|en}
--no-execute-daemon`. Language fans out two ways from that one profile:
- **Markdown side** (Quarto-resolved): prose/headings/callouts wrapped
  in `::: {.content-visible when-profile="ja|en"}`; captions via
  `#| fig-cap: "{{< meta caps.qc.KEY >}}"`; `title`/`subtitle` via
  `{{< meta title_qc >}}`; `lang:` per profile auto-localizes
  "Figure"/"図", dates.
- **Python side**: setup cell reads
  `LANG = os.environ["QUARTO_PROFILE"]` (reliable only with
  `--no-execute-daemon` — the jupyter daemon caches the first render's
  env, same gotcha the CLAS driver already documents). A `STR[LANG]`
  catalog + `T(key)` helper feeds matplotlib titles/axis labels/
  legends, table headers/rows, and `output: asis` prose.
Rejected: full string-catalog (kills prose readability), include-based
split (figures interleave prose — can't cleanly separate), separate
per-language .qmd (code duplicated → drift). Note: content-visible does
NOT prevent a gated code cell from executing — so code-cell text must
switch via `T()`, never via duplicated cells.

### Plan
- [x] `reports/_quarto-ja.yml` + `_quarto-en.yml` (+ EN defaults in
      `_quarto.yml` so a bare render = EN): `lang`,
      `title_qc`/`subtitle_qc`, `caps:` tree (namespaced per template)
- [x] monthly_qc.qmd setup: LANG (from QUARTO_PROFILE) + STR catalog +
      T() helper + language-dependent PERIOD_LABEL
- [x] monthly_qc.qmd body: FULLY converted (Methodology incl. both
      metric-definition tables, National Overview distribution + spatial
      figures, Receiver/Antenna, Absolute Qualification, Appendix —
      system events + satellites). Terminology = user-ratified glossary
      (memory/report-ja-glossary.md). Helpers (uptime_pair/_quantiles/
      hist_panel/map_grid) and asis prints all T()-ized.
- [x] matplotlib CJK: added Inter→Hiragino per-glyph fallback stack +
      pdf.fonttype=42 (mirrors monthly_free) so JA figure text isn't
      tofu. Visually confirmed two JA figures render correct Japanese.
- [x] Render monthly_qc `--profile ja` and `--profile en` (html):
      verified title/headings/section-numbers (no double-count)/prose/
      captions/tables/figures/PERIOD_LABEL/anchors all switch correctly;
      no stray English in JA; fixed a leaked `{=html}` raw-attr marker.
- [x] Update `reports/README.md`: documented the bilingual
      `--profile {ja|en} --no-execute-daemon` invocation + mechanism.
- [ ] PDF verification (xelatex) for one language — optional final gate;
      font path wired (CJKmainfont Hiragino + pdf.fonttype=42).
- [x] Apply the same pattern to monthly_free.qmd (CLAS report, was
      JA-only → now JA/EN). title_free/subtitle_free + caps.free.* in
      profiles; LANG+STR+T() in setup; Inter prepended to CJK font
      stack; all prose in content-visible; captions to {{< meta >}};
      figure labels/legends (incl. 12 network names romanized), exec/
      TTFF/hex-coverage/system-event/satellite tables, and all asis
      blocks (Rapid banner, L6, sysevents, constellation) T()-ized.
      Driver `render()`/`run_monthly()` + CLI gained `--langs`
      (default ja,en) → `--profile <lang>` into `<out>/<lang>/`.
      Verified both HTML renders: headings/section-numbers/captions/
      tables/7 figures (JA legend+axes render Japanese, EN English —
      no tofu); no stray-language leakage; 194 tests pass.

### Phase Guard
[ ] Phase 0 — "Initial Quarto template producing a usable PDF" is in
    scope; bilingual support is a refinement of the existing templates,
    not new Phase 1+ functionality.

### Done Criteria
- `monthly_qc.qmd` renders correct JA and EN HTML from one source via
  `--profile`; compute code exists once; both inspected and clean.

### Result
(Fill after completion)

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

### Plan
- [x] `analysis/qualification.py`: 99.73th percentile thresholds per
      (metric × elev bin) on a rolling QC-summary window; per-station
      NG-day count → ``qc_pass``; ``force_eval`` overlay for the CLAS
      72 evaluation set; ``out_of_service`` hard-veto layer
- [x] `configs/stations/out_of_service.toml` (4 entries)
- [x] `configs/stations/eval_periods.toml` refreshed to include
      fy2025_1st_h (72 stations, Apr-Sep 2025 per QSS report
      published 2026-01-21)
- [x] CLI ``analyze qualification`` with ``--ref-date`` /
      ``--window-days`` / ``--ng-days`` override
- [x] 12 unit tests (threshold direction, NG count, force_eval rescue,
      out_of_service veto, fallback to latest period, parquet+jsonl
      provenance)
- [x] Live: ref_date=2026-04-30, window=90d → 1083/1300 qualified
      (15 force-eval rescues, matches paper Table 2 range)
- [ ] **Followup**: 0604 / 0605 rationale capture — inherited from
      legacy ``station_stats.OUT_OF_SERVICE`` list without comment.
      Investigate (NAQU / station-side notice / decommission?) before
      removing or re-confirming the veto.
- [ ] **Followup**: methodology doc in
      ``pntmoni-docs/30-evaluation-methodology/`` (proposed name:
      ``06-station-qualification.md``). Should include: 99.73th
      rationale, force_eval semantics, window-size sensitivity,
      cross-reference to QSS Service Performance Report (the source of
      ``eval_periods.toml::fy*``)
- [ ] **Followup**: stand up a watcher / periodic check for new QSS
      Service Performance Report releases (currently semi-annual,
      ~5 months after period end). When fy2025_2nd_h publishes
      (~early Oct 2026), add CSV → re-run migration → bump
      ``methodology_version`` in ``qualification.py``
- [ ] **Followup (separate concern)**: NAQU / NAGU / NANU
      satellite-level outage notice tracking is a distinct task — not
      station qualification. Scope into its own module when integrity
      / continuity reporting comes online (per QSS Performance Report
      §4.4)
- [ ] Update aggregate scripts to consume the qualified Parquet
      and report dual metrics (raw + qualified) in monthly reports

### Phase Guard
[x] Phase 0–1 (qualification module landed; dual-aggregate hookup
    waits on monthly-report scaffolding)

### Done Criteria
- [x] A single station can be flagged qualified or not based on a
      90-day QC window + TOML overlays
- [ ] Monthly report shows BOTH raw N=1298 and qualified subset metrics
- [x] Criteria are auditable and reproducible from
      ``data/metadata/qualification.jsonl`` (full threshold table +
      methodology_version + pipeline_git_sha)

### Open Issues
- ``ng_days_max`` default ``ceil(n_days × 0.038)`` matches legacy
  weekly-sample ratio. 90-day fixed window vs dynamic window choice
  needs revisit alongside the first 2-3 monthly reports (does the
  threshold's stability deteriorate at month boundaries?)
- "Qualified" definition may evolve — tied to
  ``methodology_version = "qual-v1"`` in the parquet schema metadata
  so cross-report comparability is auditable

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

## [Phase 1+] Task: Migrate convbin → MRTKLIB ``mrtk convert``

### Goal
Replace the RTKLIB ``convbin`` invocation in the QC pipeline
(``qc/_teqc.py``) with the MRTKLIB ``mrtk convert`` subcommand.
Functional behaviour stays the same (RINEX 3 → 2 with ``-y R -f 5
-od -os -oi -ot -ol``); the win is consolidating onto MRTKLIB so the
pipeline depends on a single GNSS-library codebase.

### Plan (sketch)
- [ ] Build MRTKLIB ``mrtk`` (``apps/convbin/`` provides convbin.c;
      verify whether the new umbrella ``mrtk convert`` interface
      exists or needs to be wrapped)
- [ ] Stage at ``vendor/teqc/mrtk_convert`` (or replace the existing
      ``vendor/teqc/convbin`` symlink)
- [ ] Update ``DEFAULT_CONVBIN`` in ``qc/_teqc.py`` and CLI default
- [ ] Run a side-by-side check on one DOY: bit-identical or numerically
      indistinguishable v2 OBS/NAV outputs vs RTKLIB convbin
- [ ] Update lessons.md if any flag-set difference surfaces

### Phase Guard
[ ] Phase 1+ (current QC works fine with RTKLIB convbin; this is
    consolidation, not feature work)

### Open Issues
- ``mrtk convert`` may have a different CLI surface than convbin
  (positional arg ordering, default ``-d`` semantics) — wrap if needed
- The migration should be a single small commit, easy to revert

---

## [2026-05-10] Task: Production aux-data dir + igs20.atx acquisition

### Goal
Stage a writable ``configs/aux_data/`` directory containing the
official aux files referenced by the production config
``configs/kinematic_p30.conf`` (``igs20.atx``,
``clas_grid_003.def``), so production processing can run with
``--data-dir configs/aux_data`` instead of falling back to the
verify config.

### Plan (sketch)
- [ ] Acquire official igs20.atx from
      ``https://files.igs.org/pub/station/general/igs20.atx``;
      record sha256 in a provenance log
- [ ] Source ``clas_grid_003.def`` (CAO/MELCO) — currently CLASLIB
      ships only ``clas_grid.def``; check if 003 is a newer drop
      with extra grid points or just a rename
- [ ] Place under ``configs/aux_data/`` (gitignored if large; small
      files committed with provenance comment)
- [ ] Optional: small acquire CLI (``pntmoni-pipeline acquire
      igs-antex --version igs20``) so re-acquisition is reproducible
- [ ] Document the production run recipe in README.md

### Phase Guard
[ ] Phase 0 (production-grade processing depends on this)

### Open Issues
- ``igs14_L5copy.atx`` (CLASLIB-shipped) is content-equivalent to
  ``igs20.atx`` (per user). Use that as a fallback while official
  acquisition is set up — but track it as "stand-in", not the
  canonical file
- ``clas_grid_003.def`` source path/URL is unconfirmed; user contact
  with CAO/MELCO may be needed

---

## [2026-05-10] Task: Re-run downstream chain with F5.1 reference for 2026-04-01

### Goal
The current ``data/processed/{epoch_errors, accuracy, accuracy_network,
ttff, ttff_network, *_monthly}/`` Parquets for 2026-04-01 were
computed against the previous trailing-7-day F5 (ITRF2014) reference.
After the F5.1 acquisition the reference at the same path is now
full-window F5.1 (ITRF2020). Downstream Parquets should be re-run for
internal coherence and to produce the production-grade verify number.

### Plan
- [ ] ``analyze epoch-errors --date 2026-04-01 --mode kinematic_p30_verify``
- [ ] ``analyze epoch-errors --date 2026-04-01 --mode kinematic_p30_ttff_verify``
- [ ] ``analyze accuracy --date 2026-04-01 --mode kinematic_p30_*``
- [ ] ``analyze ttff-stats --date 2026-04-01 --mode kinematic_p30_ttff_verify``
- [ ] ``analyze monthly --month 2026-04 --mode kinematic_p30_*``
- [ ] Compare numbers against the previous run; document the
      ITRF2014→ITRF2020 shift's effect on percentile errors in
      lessons.md
- [ ] Verify provenance JSONLs accumulate cleanly (append-only)

### Phase Guard
[x] Phase 0 (verify run with the latest reference)

### Done Criteria
- Downstream Parquets recomputed against ITRF2020 reference
- Provenance log records both runs
- Differences explained in lessons.md (frame difference is mostly
  intercept; cm-level effect on percentiles)

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

## [Phase 0–1] Task: NAQU / NAGU / NANU satellite outage acquisition

### Goal
Acquire and normalise per-satellite outage notices from the three
constellation-specific channels (NANU/GPS, NAGU/Galileo, NAQU/QZSS)
into a canonical Parquet store that both this pipeline and the web
calendar can consume.

### Result (Phase 0 producer side complete, 2026-05-16)
- `acquisition/satellite_outages/` with parsers for all three sources;
  CLI `acquire satellite-outages [-c gps|gal|qzs|all] [-y YYYY]`
- Live run verified: NAQU 2025 (568 raw → 310 events), NANU 2025
  (84 parsed), NAGU RSS (6 recent). Outputs at
  `data/processed/satellite_outages/{raw_notices/,events.parquet}` +
  provenance at `data/metadata/satellite_outages.jsonl`
- Cloud + web wiring tracked in
  [`pntmoni-docs/tasks/cross-repo-todo.md`](../../pntmoni-docs/tasks/cross-repo-todo.md)
  (ADR 0012 follow-ups)

### v2 follow-ups (this repository)
- [ ] `analysis/clas_availability.py`: helper computing CLAS-supply
      availability from L6 outage simultaneity across the broadcaster
      set (currently SVN002/003/004/005 per Service Performance Report
      Table 5). Anchors the methodological distinction documented in
      `tasks/lessons.md` 2026-05-16 "NAQU L6 outages do NOT imply CLAS
      unavailable". Encode the broadcaster set in a config TOML so
      future constellation changes (new QZS launches, GEO swaps)
      surface as a config diff rather than a code change
- [ ] NAQU `event_type` taxonomy refinement: 78 % of normalised
      events currently land in `other` because the NAQU type set is
      large (FCSTSUMM, FCSTCANC, UNUNOREF, FCSTRESC, …). Extend
      `events._TYPE_MAP`, bump `methodology_version` to
      `outage-norm-v2`, and re-run normalisation
- [ ] GENERAL-type NANU handling: ~2-5 per year are free-text
      announcements with no DTG / SVN / window. v2 may store them as
      raw notices with `fetched_at` as `published_at` and a sentinel
      `notice_type = "GENERAL"`; for v1 the operational information
      gain is minor
- [ ] NAGU historical backfill from
      `https://www.gsc-europa.eu/system-status/user-notifications-archived`
      (HTML scrape) when historical depth becomes required (e.g.
      cross-year continuity stats)
- [ ] SVN ↔ block mapping table to populate `block` field on
      `OutageEvent` (currently always None). Lives well as a small
      curated TOML under `configs/`

### Motivation
- Web product: unified satellite-outage calendar UI (Phase 0 scope per
  `pntmoni-docs/CLAUDE.md`)
- Pipeline self-consumption: continuity / integrity stats in monthly
  report (mirrors QSS Performance Report §4.4 / §4.5) + anomaly
  attribution

### Plan (sketch)
- [ ] `acquisition/satellite_outages/nanu.py`: USCG NAVCEN scrape +
      parser
- [ ] `acquisition/satellite_outages/nagu.py`: EUSPA / GSC feed +
      parser
- [ ] `acquisition/satellite_outages/naqu.py`: Cabinet Office / QSS
      web scrape + parser
- [ ] `acquisition/satellite_outages/events.py`: normalise raw
      notices → canonical `OutageEvent` per
      `pntmoni-docs/40-data-schemas/satellite-outages.md`
- [ ] CLI: `pntmoni-pipeline acquire satellite-outages
      [--constellation gps|gal|qzs]`
- [ ] Outputs:
  - `data/processed/satellite_outages/raw_notices/{src}/{YYYY}/{YYYY-MM}.parquet`
  - `data/processed/satellite_outages/events.parquet`
  - `data/metadata/satellite_outages.jsonl`
- [ ] Unit tests for each parser + the normalisation rules
- [ ] Historical backfill from each constellation's accessible
      archive (depth varies — investigate during impl)

### Architecture / dependencies
Per [`pntmoni-docs/70-decisions/adr-0012.md`](../../pntmoni-docs/70-decisions/adr-0012.md):
- Pipeline = single producer
- `pntmoni-cloud` schedules daily acquisition + uploads to GCS
- `pntmoni-web` reads cloud API; does NOT scrape directly
- The shared interface IS the Parquet schema, NOT a code library

### Phase Guard
[ ] Phase 0–1 (Notice calendar prototype is in Phase 0 scope per
    `pntmoni-docs/CLAUDE.md`; monthly-report continuity / integrity
    consumption is Phase 1+)

### Done Criteria
- Three parsers produce `raw_notices.parquet` records validated
  against the schema doc
- `events.py` normalises raw → events with deterministic event_id
- Pipeline can answer "was QZS-3 healthy on 2026-04-15?" locally
  in <1s
- Cloud upload + API endpoint wired up (in `pntmoni-cloud`)

### Open Issues
- Backfill horizon per source — NANU long-archived at USCG, NAQU /
  NAGU archive depth TBD
- SVN ↔ PRN historical mapping across satellite generation changes
  (especially QZS-1R replacement) — needs a small reference table
- Severity classification edge cases (e.g. multi-signal partial
  outages) — refine `events.py` rules as live data surfaces
- Web TypeScript type sync: schema doc is hand-curated; consider
  a generator step if drift becomes a problem

---

## [2026-05-16] Task: R5 / R5.1 (Rapid) acquisition + 速報 ENU computation

### Goal
Per ADR 0013 (`pntmoni-docs/70-decisions/adr-0013.md`), the Free Monthly
速報 report is built from GSI's **Rapid** coordinate solution lineage
(R5/R5.1) so monthly numbers can be published ~1 week after end-of-month
instead of waiting ~1 month for the Final (F5/F5.1) snapshot. The same
month is later republished as 続報 against F5.1 once available. The
pipeline must therefore (a) acquire R5/R5.1 alongside F5/F5.1 and (b)
compute reference coordinates + ENU from R5.1 without overwriting the
Final-variant outputs that will land later.

### Plan
- [x] `acquisition/geonet_f5.py`: extend `F5_VARIANTS` with `r5` /
      `r5_1`; add `is_rapid` field on `F5Variant`; add
      `rapid_variant_for_date()` mirroring `variant_for_date()` for the
      ITRF2014→ITRF2020 switch
- [x] CLI: `pntmoni-pipeline acquire r5 [--variant r5|r5_1]` (default
      `r5_1` for post-2026-04-01 work); `acquire f5` retains its
      f5/f5_1-only scope
- [x] `analysis/_reference_coords.py`: thread `variant` through
      `compute_for_target` / `compute_for_targets`; record in the
      `ComputeResult.variant` field and on the parquet row; output
      paths are now **variant-namespaced**
      (`{root}/{variant}/{year}/...`) so R5.1 速報 and F5.1 続報 coexist
- [x] CLI `analyze reference-coords --f5-variant` accepts the new
      values (`r5`, `r5_1`, `auto-rapid`); spanning the ITRF2014→ITRF2020
      switch still fails loud per the Final flow
- [x] `analysis/_epoch_errors.find_reference_coords_parquet`
      variant-aware with auto-resolve preferring Final (F5.1 > F5 > R5.1
      > R5); CLI `analyze epoch-errors --ref-variant r5_1` for explicit
      Rapid lookup
- [x] One-shot migration of 3 existing reference_coords parquets into
      the new variant subdirs (f5/, f5_1/)
- [x] Tests: variant routing for R5/R5.1, rapid variant_for_date,
      output paths namespaced, find_reference_coords_parquet picks
      variant. 25/25 reference + epoch_errors green; 112/112 suite green
- [x] Live: `acquire r5 --year 2026 --variant r5_1` against terras.gsi
      verified the assumed FTP path `/data/coordinates_R5.1/2026/` —
      1306 .pos files, ~25 MB, data through 2026-05-15 (vs F5.1 lag
      ~1 month). `SOLUTION_ID = R5(GPS)`, `EPHEMERIS = IGR`, otherwise
      structurally identical to F5.1
- [x] Live: `analyze reference-coords --date 2026-04-01 --f5-variant
      auto-rapid` → 1301-station parquet at
      `data/processed/reference_coords/r5_1/2026/20260401.parquet`,
      fixed_days_used=15/15
- [x] R5.1 vs F5.1 empirical delta recorded in lessons.md
      (p50=1.32 mm 3D, p95=1.66 mm)
- [x] 30-day downstream chain for 2026-04 (epoch-errors × 2 modes →
      accuracy → ttff-stats → monthly for kinematic_p30_ttff_verify):
      30/30 days OK, 32 min wall, single in-process driver at
      `/tmp/r51_april_driver.py` (ad-hoc, not committed). First
      national monthly aggregate landed at
      `data/processed/accuracy_monthly/.../202604.parquet` etc.

### Open Issues / followups
- [x] `kinematic_p30_verify` monthly (verify=97.34% vs ttff_verify=75.44%
      fix_rate, lessons 2026-05-17)
- [x] `eval_only` / `qualified` station_set population via the new
      `--qualification` flag (lessons 2026-05-17 "registry
      qualification-merge"). 速報 publishes `qualified` as the
      headline subset; `all` as the permissive reference;
      `eval_only` as the QSS-aligned reproducibility set
- engine_version label `v0.8.3-pntmoni-1-dirty` on the R5.1-rerun
  epoch_errors is **the driver's stated label**, not the binary that
  produced the underlying .pos files. For repackaging runs the
  label may understate the actual provenance; track if it matters
- Disk: post-batch `free_end = 16.7 GB` (started at 29.9 GB; net
  +13 GB on disk for 2 modes × 30 days of epoch_errors + small
  Stage-2 + monthly parquets). Inside the 15 GB safety threshold
  but margins are thin — consider `.pos` archival to
  /Volumes/Humphrey-1/ once the cube is verified

### Phase Guard
[x] Phase 0–1 (Rapid ingestion path is the architectural scaffolding
    ADR 0013 requires for Phase 1's Free Monthly 速報 launch)

### Done Criteria
- [x] `acquire r5` and `acquire f5` produce disjoint local archives
- [x] reference_coords parquets are variant-namespaced so 速報/続報
      coexist
- [ ] First live R5.1 acquisition succeeds (or the assumed remote path
      is corrected after a clear failure)
- [ ] First R5.1-based ENU parquet rendered and compared against an
      F5.1 baseline once the latter is available

### Open Issues
- The R5 / R5.1 FTP paths
  (`/data/coordinates_R5/GPS/`, `/data/coordinates_R5.1/`) are
  reasoned by analogy with F5 / F5.1 — to be confirmed on first live
  run. The fetch already raises a clear `FileNotFoundError` if the
  directory is empty / missing, which surfaces a wrong path quickly
- R5 / R5.1 file format is assumed structurally identical to F5 /
  F5.1 (SITE/INF + SOLVER/INF + +DATA block; same row shape). The
  `_f5_reader` is format-agnostic past the +DATA marker so this
  should hold; verify on first read and record the
  `SOLVER/INF::SOLUTION_ID` string (likely `R5(GPS)` vs `F5(GPS)`)
  in a lesson if it diverges in any unexpected way
- After the first 速報 ENU run, document the R5.1 vs F5.1 numerical
  delta (expected ~mm-to-low-cm at aggregate, larger near recent
  deformation events) in lessons.md so the Free 速報 → 続報
  republication pattern's typical magnitude is on-record

---

## [2026-05-25] §6 L6 alerts + report injection + Free-tier build-out (v1.0.0 monthly readiness)

Goal: close the remaining "documented-but-not-implemented" gaps in the
v1.0.0 methodology so the monthly report can be produced as written.
Phase Guard: Phase 0 (first trial monthly report). Refs: methodology
§5/§6/§7, ADR 0013 + Postscript (hex Free viz), ADR 0006 Postscript
(comparison stays in the half-yearly Archive, not monthly).

### todo#1 — L6 broadcast alert extraction & aggregation (§6)

Mechanism: `ssr2osr -dump` emits `parse_cssr_*.csv`;
`parse_cssr_header.csv` (ofp[10], cssr.c:4348/4352) carries the
`Alert Flag` column (+ Epoch Time, PRN, L6 msg type, etc.).

- [ ] Build `ssr2osr` for macOS: `cd vendor/pntmoni-claslib/util/ssr2osr && make`
      (mirrors rnx2rtkp; the `_POSIX_C_SOURCE` working-tree patch
      enables the macOS compile). Add a binary discovery + build-hint
      path analogous to `processing/_binary.py`.
- [ ] New module (`analysis/_l6_alerts.py` or a new `anomaly/` pkg):
      locate the period's L6 input (reuse `acquisition/qzss_l6` paths)
      → run `ssr2osr -dump` → parse `parse_cssr_header.csv` → aggregate
      `Alert Flag` (monthly count, daily/epoch time series, per-PRN
      breakdown) → cross-reference NAGU/NANU/NAQU
      (`acquisition/satellite_outages`) by time × satellite → write
      `l6_alerts` parquet + `l6_alerts.jsonl` provenance (ssr2osr
      version + input SHA-256).
- [ ] CLI: `pntmoni-pipeline analyze l6-alerts --period YYYY-MM`.
- [ ] Unit tests (fixture `parse_cssr_header.csv`; aggregation +
      cross-ref).
- [ ] Verify on real 2026-04 L6 data; record sample output.

### todo#2 — Report render driver + param injection (§7.2/§7.4, §5, §6)

- [ ] Report-render driver (CLI `report monthly --period --stream`):
      gather monthly parquets (accuracy_monthly, ttff_monthly,
      qualification, reference_coords, l6_alerts) → compute
      `config_hash` (`config_hash.compute_config_hash`), record full
      digest to `processing.jsonl`, pass 16-char display → assemble
      Quarto params (period, stream, engine/qc/refcoord/methodology
      versions, config_hash, headline metrics, alert summary,
      data_mode) → render `monthly.qmd` via Quarto (`--execute-params`)
      → PDF + HTML.
- [ ] Replace `monthly.qmd` synthetic placeholders with param-bound
      real data loading for the sections that have data (§5, §6, §7.4).
- [ ] Verify: render 2026-04 (R5.1) report with real config_hash +
      alert counts.

### todo#3 — Free-tier hex-grid spatial viz (ADR 0013 Postscript) — cell size is the crux

- [ ] **DECIDE cell-size + min-stations-per-cell policy** (shared with
      Product 2 GNSS QC). Options: (a) equal-area hex via H3 resolution;
      (b) fixed geographic km; (c) data-driven (coarsest resolution
      keeping most populated cells ≥ k stations) + suppression
      threshold k. Needs discussion + empirical tuning on the GEONET
      ~1300-station distribution.
- [ ] Define the cell aggregate statistic consistent with §5.1
      (pooled-epoch percentile over the cell's stations — not a second
      station-unit step).
- [ ] Implement a single shared hex-grid rendering path (Product 1 Free
      + Product 2); fixed color scale per metric; empty/suppressed
      cells visually distinct.
- [ ] Wire into `monthly.qmd` Free spatial section (Free = hex; Pro =
      per-station scatter retained).
- [ ] Verify visually (sample hex map for 2026-04).

### Open decisions (resolve before the todo#3 build)

- **Cell-size method + min-stations-per-cell threshold** — the shared
  Product 1/2 question. Tentative: evaluate H3 resolutions against the
  GEONET distribution, pick the coarsest that keeps most populated
  cells ≥ k (k ~3–5, TBD). Needs sign-off.
- Module homes: `analysis/_l6_alerts.py` vs new `anomaly/`; report
  driver as new `cli/report.py` vs extending `cli/analyze.py`.
- ssr2osr binary kept as a local build artifact (out of git), like
  rnx2rtkp — confirm.

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

---

## [2026-06-02] Task: Free Monthly report — real-data render polish + constellation status

Goal: bring the Free Monthly report to a state where 2026-04 (rapid)
can be issued end-to-end with real data in every panel that has the
inputs available. Phase Guard: Phase 0. Refs: methodology §5/§6/§7.4,
ADR 0013 + Postscript (hex Free viz).

- [x] Hex spatial figure: switch from manual MplPolygon loop to
      `matplotlib.hexbin` (`reduce_C_function=p95`); per-station-day
      stratified subsample bounds memory; pre-project to Albers
      because hexbin ignores cartopy `transform=`
- [x] Hex thresholds reframed against the CLAS spec
      (緑 ≤12cm / 黄 12–24 / 赤 >24, vertical 24/48); spec basis
      explained in §空間分布 prose
- [x] Split horizontal & vertical hex into two separate figures
- [x] Figure 1: real GEONET station distribution + CLAS 12-network
      grid points (cartopy Albers, plot_map.py vendored data)
- [x] Stream-aware reference_coords lookup: `('rapid', '2026-04')→r5_1`,
      `('final', '2026-04')→f5_1` via `stream_to_frame_subdir()`
- [x] 速報 banner — callout-warning when STREAM == 'rapid'
- [x] TTFF driver fix: pair the accuracy mode with its `_ttff_verify`
      twin via `_ttff_mode_for(mode)` (the continuous-mode TTFF
      column was meaningless ≈ 0s)
- [x] TTFF histogram → CDF (matches §5.1 accuracy CDF axes
      convention) using real per-window TTFF re-derived at render
      time from ttff-mode epoch_errors
- [x] NAGU/NANU/NAQU appendix table now reads
      `satellite_outages/events.parquet` filtered to the report period
- [x] §衛星一覧 GPS / QZSS / Galileo tables driven by a new
      `acquire constellation` CLI that scrapes the three operator
      pages (NAVCEN / QSS DoD / GSC Europa) into a unified parquet;
      11 unit tests with vendored HTML fixtures
- [x] CJK font fallback (Hiragino → Yu Gothic → Noto CJK)
- [x] Synthetic preview path uses real station coords + per-station
      baseline variation so previews render meaningful spread
- [x] Cleanup: removed unused synthetic setup vars (NETWORK_POLYGON,
      inside_network, station_lats/lons, station_ids, station_h95/v95,
      last6_start_idx, yago_idx, trend_*, current_idx)
- [x] methodology v1.0.0: §5.1 — hex color-threshold table added,
      §5.2 — TTFF table-vs-figure aggregation difference documented

### Verification

End-to-end render for 2026-04 rapid:
- `pntmoni-pipeline acquire constellation` → 32 GPS + 5 QZSS + 32 Gal
- `pntmoni-pipeline report monthly --period 2026-04 --stream rapid
   --mode kinematic_p30_verify --render` → 82 MB HTML, all panels
  populated, no synthetic-preview notices except where data missing
- 16 unit tests across hex_grid + report_driver + constellation_status
  all green

### Open Issues (deferred)

- **PDF render** still fails (driver invokes HTML+PDF; PDF path errors
  on LaTeX/typst — HTML works). Either gate PDF behind a flag or fix
  the typst toolchain.
- **L6 alerts**: April raw L6 not yet acquired (`data/raw/l6/` empty).
  Run `acquire l6 --date YYYY-MM-DD` × 30 then
  `analyze l6-alerts --period 2026-04`.
- **Constellation status snapshot freshness**: currently manual.
  Consider monthly cron via `loop` or a pre-render hook in driver.
- **TTFF table P99 vs figure P99 gap** (480s vs 540s): qualified-set
  filter difference; documented in methodology §5.2 but could be
  unified if a single semantic is preferred.
- **近月のトレンド** still Coming Soon — needs the Phase 0/1
  retroactive monthly processing pipeline to populate 2025-04 onwards.
- **相互検証** still Coming Soon — Phase 1+, requires MRTKLIB
  submodule + parallel evaluation pipeline.

---

## [2026-06-02] Task: Daily orchestration (acquire→process→QC) + backfill automation

### Goal
Stand up `pntmoni-pipeline daily --date` and
`pntmoni-pipeline backfill --start --end` that drive the existing
per-DOY building blocks (acquire RINEX/BRDC/L6 → CLASLIB positioning →
teqc QC → QC summarize) idempotently and unattended, plus a launchd
schedule for nightly daily runs and a resumable backfill over historical
ranges. Replaces the ad-hoc `/tmp/*_driver.py` scripts. **Report
generation is explicitly out of scope** (deferred per user — report
content still unsettled).

### Phase Guard
[x] Phase 0 — operational automation of already-landed Phase 0 building
    blocks (acquisition, CLASLIB processing, teqc QC). No new
    analysis/report capability; purely orchestration + scheduling.

### Design notes (grounding)
- Per-day units are already idempotent + date-parameterised + bounded-
  parallel (`process claslib` skips existing `.pos`; `qc teqc` skips
  existing `.{yy}S`; `qc summarize` writes one parquet). So daily =
  "call the units in dependency order"; backfill = "iterate days".
- Backfill runs **days sequentially** — each day already saturates cores
  via the per-station thread pool, so day-level concurrency would
  oversubscribe this (founder's daily-driver) machine. Resumability comes
  for free from the existing skip-if-exists behaviour.
- Dependency order within a day:
  `acquire {rinex,brdc,l6}` → { `process claslib` (×modes), `qc teqc` } →
  `qc summarize`. process and teqc both consume RINEX; run sequentially
  to avoid CPU oversubscription.

### Plan
- [x] `orchestration/` package (new):
  - [x] `_steps.py` — thin callables wrapping existing engine entrypoints
        (`geonet_rinex.fetch`, `cddis_brdc.fetch`, `qzss_l6.fetch`,
        `claslib_engine.process_doy`, `_teqc.process_doy`,
        `_summary.summarize_doy`) → uniform `StepResult`
        (name, ok/skipped/failed, wall, error). Never raises.
  - [x] `daily.py` — `run_day(date, modes, *, skip_acquire, force,
        workers)` runs steps in dependency order, collects per-step
        status, writes one record → `data/metadata/orchestration.jsonl`
  - [x] `backfill.py` — `run_range(start, end, ...)` iterates days
        sequentially, short-circuits already-complete days, continue-on-
        error, returns a per-day status table + final summary
- [x] CLI: top-level `pntmoni-pipeline daily` and `... backfill`
      (registered in `cli/__init__.py`; new `cli/run.py`).
      `daily` defaults to `today − 2d` when `--date` omitted.
- [x] Idempotency: rely on existing per-unit skip; `is_day_complete()`
      day-level short-circuit (qc_summary parquet + per-mode `.pos`) +
      `--force` passthrough
- [x] Failure isolation: one station/day failure never aborts the run;
      collected + reported; CLI exits non-zero if a hard stage fails
- [x] Observability: one JSONL record per day-run + a per-run log file
      under `data/logs/`
- [x] Scheduling: `configs/launchd/com.pntmoni.daily.plist` template +
      `scripts/run_daily.sh` (caffeinate wrapper) + `configs/launchd/
      README.md`; failure notification via `_notify.py` (log + optional
      `PNTMONI_NTFY_URL`)
- [x] Tests: `tests/unit/test_orchestration.py` — status rollup,
      sequencing, dependency gating, short-circuit, continue-on-error
      (17 tests; full suite 186 green)
- [x] Verify (integration boundary): live `daily --date 2026-04-01
      --skip-acquire` exercised the real engines on a cold-tiered day —
      failure isolation, `qc_summarize` gating, JSONL record, log file,
      and exit-code 1 all confirmed
- [ ] Verify (happy path, heavy): one fresh `daily` for a recent date
      (real ~7 GB acquire + 1298×2 process) — deferred; needs a real
      acquisition run (offer to the user)

### Done Criteria
- `daily --date YYYY-MM-DD` runs acquire→process→qc end to end and is a
  cheap no-op on re-run
- `backfill --start --end` processes a range, is resumable, continue-on-
  error, prints a final per-day summary
- launchd plist installs + triggers a nightly run (machine-awake caveat
  documented)
- Report generation NOT included
- Tests green

### Result (2026-06-02)
- New `orchestration/` package + top-level `daily` / `backfill` CLI; the
  ad-hoc `/tmp/*_driver.py` pattern is now a first-class, idempotent,
  failure-isolating driver. 17 new unit tests, 186 total green.
- Confirmed decisions (all recommended): daily = acquire→process→QC;
  modes = `kinematic_p30_verify` + `kinematic_p30_ttff_verify`; launchd
  scheduling + ntfy failure notification included.
- **Key finding:** `claslib_engine.process_doy` validates required raw
  artefacts (L6 AX, BRDC, RINEX) **up front**, before the per-station
  `.pos` skip. So a re-run is only cheap when `is_day_complete()`
  short-circuits it (qc_summary parquet + per-mode `.pos` present). In
  normal orchestrated operation a finished day always has the qc_summary,
  so this holds; but a *partially* finished day whose raw was cold-tiered
  will hard-fail on re-run (process step) rather than skip. Acceptable
  edge — surfaced as a failed step, not a silent pass.

### Open Issues / to confirm
- Unattended credentials: GSI FTP (`GSI_FTP_USER/PASSWORD`) + Earthdata
  (`.netrc`) must be present in the launchd environment (sourced from
  `$REPO/.env` by `run_daily.sh`)
- macOS launchd does not fire while the machine is asleep —
  `caffeinate` (idle, in-run) + `pmset repeat wakeorpoweron` (wake at
  02:55) documented as the mitigation in `configs/launchd/README.md`
- Disk growth: `.pos` accumulates during backfill; storage tiering still
  pending (tracked separately). Note the cold-storage interaction with
  process_doy's upfront artefact check (Result above) when backfilling
  ranges whose raw inputs were tiered out.
- Happy-path live run still owed once a real acquisition is run for a
  recent date.

## [2026-06-02] Free QC report — port CLAS hexbin spatial maps

### Context
CLAS Free report (`monthly_free.qmd`) got a much-improved spatial layer:
matplotlib `hexbin` pre-projected into Albers Equal-Area, replacing the
old per-station scatter. The Free **QC** report (`monthly_qc.qmd`) still
uses cartopy scatter in Lambert Conformal. Port the hexbin rendering
method to the QC report's 9 spatial metric maps.

### Confirmed decisions (user, 2026-06-02)
- Per-hex value = **median of station-monthly values** in the cell
  (QC has per-station scalars, not poolable epochs → median, not p95).
- Colour = **continuous per-metric colorbar** (Normalize / LogNorm),
  NOT CLAS's discrete green/amber/red — QC metrics have no absolute spec.
- Scope = **all 9 spatial maps** (SN1/2/5, SN7, MP12/21, MP15/51,
  MP17/71, cycle_slips_core). Network station map (fig-network) stays scatter.
- Language = **English** (unchanged). Port the drawing method only.

### Reference (what to copy from monthly_free.qmd:853-944)
- Projection: `ccrs.AlbersEqualArea(central_longitude=137,
  central_latitude=35, standard_parallels=(30,43))`.
- Pre-project (lon,lat)→Albers metres ONCE; hexbin ignores cartopy
  `transform=` and bins in axes coords (the key gotcha).
- `ax.hexbin(x,y, C=value, reduce_C_function=<median>, gridsize=50,
  edgecolors="white", linewidths=0.3, mincnt=1, ...)`.
- `gridsize=50` over ~3000 km Albers width → ~60 km hex cells.

### Plan
1. Add an Albers projection + `japan_hex_axes()` styling helper to the
   QC setup cell (mirrors CLAS land/ocean/coastline chrome). Keep the
   existing Lambert `JAPAN_PROJECTION`/`japan_axes` for fig-network.
2. Pre-project `station_monthly` (lon,lat) → Albers (x,y) once in setup.
3. Rewrite `map_grid()` helper: replace `ax.scatter(...)` with
   `ax.hexbin(x_aea, y_aea, C=station_monthly[m],
   reduce_C_function=np.median, gridsize=50, cmap, norm, mincnt=1,
   edgecolors="white", linewidths=0.3)`. Keep the per-metric
   `norm_factory` + shared colorbar logic intact.
4. Rewrite the standalone cycle-slips map (fig-spatial-slips, currently
   inline scatter) the same way, keeping its `LogNorm`.
5. mincnt sizing: with median over stations, set `mincnt=1` (a cell with
   ≥1 station shows its median). Confirm sparse-cell behaviour visually.
6. Update fig captions + the §Spatial callout to say "60 km hex cells,
   per-cell median of station-monthly values".
7. Render QC report to HTML (+ PDF spot check) and inspect all 9 maps
   visually — coastline alignment, hex size, colorbar range, sparse
   edges (Hokkaido / Okinawa / Ogasawara).

### Verification gate
- `quarto render reports/templates/monthly_qc.qmd --to html` succeeds.
- All 9 hex maps render with correct Albers coastline + filled cells.
- Colorbars match the existing per-metric ranges (no regression).
- PDF path also renders (xelatex) without the U+2264 issue (QC legend
  uses no ≤/> mathtext, but verify no new glyph gaps).

### Open question to confirm before coding
- QC loads data directly from `data/processed/qc_summary` (its own
  `data_root` param), NOT via driver.py's INPUTS bundle like the CLAS
  report. Leave that wiring as-is (out of scope), or also bring QC under
  the driver? Proposing: leave as-is — orthogonal to the hex port.

### Result (2026-06-02)
- `monthly_qc.qmd` ported: added `JAPAN_HEX_PROJECTION`
  (`ccrs.AlbersEqualArea`, 137E/35N, parallels 30/43) + one-time
  pre-projection of `station_monthly` (lon,lat)→Albers (`_x_aea`/`_y_aea`)
  in setup; reused the projection-agnostic `japan_axes` chrome. `map_grid`
  scatter→`hexbin(C=…, reduce_C_function=np.median, gridsize=50, mincnt=1,
  edgecolors="white")` with the per-metric `norm_factory`+colorbar kept
  intact; the standalone cycle-slips map gets the same treatment with its
  `LogNorm`. Per-metric NaN dropped before each hexbin so a cell median
  is over real obs only. Added a §Spatial lead paragraph + updated the
  free-tier callout. `fig-network` stays Lambert scatter (per plan).
- **Verified (isolated render):** the real qc_summary is a symlink to an
  unmounted external drive (`/Volumes/Humphrey-1/…`), so a full qmd render
  isn't possible right now. Verified the changed code path in isolation
  (`/tmp/verify_qc_hex.py`) against 350 synthetic stations — Albers
  coastline alignment, gridline labels, Normalize + LogNorm colorbars,
  white-edged median hexes, and the NaN-dropna path all render correctly.
- **Real-data render DONE (Humphrey-1 mounted):** rendered
  `monthly_qc.qmd` against real April-2026 data (1,298 stations × 30
  days) to **both HTML and PDF** — no errors. Extracted the spatial
  figures from the HTML and confirmed: dense contiguous Albers hex
  cells tracing the full archipelago (Hokkaido→Okinawa + southern
  islands), white edges, per-metric Normalize colorbars (SN/MP) and
  LogNorm (cycle slips), `fig-network` still Lambert scatter. `gridsize=50`
  / `mincnt=1` look right on the real extent — no tuning needed. PDF
  (xelatex) embeds the cartopy/hexbin figures cleanly; QC legends use
  continuous colorbars (no ≤/> mathtext) so the Hiragino U+2264 issue
  doesn't apply.
- **Dependency fix:** `md_table()`→`df.to_markdown()` needs `tabulate`,
  which was missing from `pyproject.toml`. Added `tabulate>=0.9` to
  `dependencies` + `uv sync`. Also note: Quarto must use the project
  venv — render with `QUARTO_PYTHON=$REPO/.venv/bin/python3` (the bare
  `quarto` picks up a system Python without jupyter/yaml/tabulate).

## [2026-06-02] Free QC report — scope review vs ADR 0009 / 0011 / 0013

Reviewed monthly_qc.qmd against the Product 2 (GEONET Quality Monitoring)
free-tier design scope.

### Authoritative scope docs
- `pntmoni-docs/70-decisions/adr-0009.md` Postscript — Product 2 free-tier
  structure (distributions, daily trends, hex-grid spatial, receiver/
  antenna inventory; per-station = Pro).
- `adr-0013.md` Postscript / `00-overview/04-current-status.md` L221-234 —
  **minimum-stations-per-cell suppression is MANDATORY** (shared Product 1
  / Product 2 hex requirement; "1 cell = 1 station" risk).
- `adr-0011.md` — Absolute Station Qualification: rolling 3-month × daily
  (n≈91), 99.73 pct; deviation from NAVIGATION 2026 weekly-over-year.

### Findings + actions
- 🔴 **mincnt=1 violated the mandatory min-stations-per-cell suppression.**
  Fixed: added `MIN_STATIONS_PER_CELL = 3` (setup) and applied to both the
  map_grid and cycle-slips hexbin calls + §Spatial prose. Sparse southern-
  island single-station cells now suppressed; mainland coverage retained.
- 🟡 **Qualification "Coming Soon" text was pre-ADR-0011** ("53-week annual
  rolling / weekly metrics over the rolling year"). Updated to rolling
  3-month × daily (n≈91) + the deliberate-deviation rationale.
- 🟡 **Recent Trends removal vs ADR 0009 "daily trends"** — user confirmed
  keep removed; availability/visibility daily bars retain a daily-trend
  surface. No action.
- 🟢 In scope: hex median aggregation, fixed per-metric color scale, blank
  empty cells, no station IDs/values, distributions, aggregate equipment
  inventory, correct exclusions (positioning/TTFF/integrity/cross-engine).
- 🟢 NAGU/NANU/NAQU + satellite list (Appendix): beyond ADR 0009's free
  list but informational context (no per-station QC data); consistent with
  the CLAS report + ADR 0012. Acceptable addition.

### CLAS (Product 1) station-count suppression — DONE (2026-06-02)
- `monthly_free.qmd` hex used `mincnt=50` = an *epoch* count (C = pooled
  epoch errors), orthogonal to anonymity — a 1-station cell (tens of
  thousands of epochs) passed it. Now implements the ADR 0013 mandate:
  - HEX_EPOCHS_DF retains `station`; a `_stcode` (factorized id) is
    pre-computed alongside `_x_aea/_y_aea`. Synthetic fallbacks carry a
    station column too (coarse path = 200 stations × 25 epochs).
  - `_render_hex_panel` runs two hexbins on an identical grid (same
    x/y/gridsize/extent/mincnt=1 → bin arrays align, verified
    `offsets identical: True`): pass 1 (undrawn) computes distinct-station
    count per cell (`reduce_C_function=np.unique(v).size`); pass 2 is the
    p95 metric layer. Cells with < MIN_STATIONS_PER_CELL (=3, equal to
    Product 2) are dropped via `set_offsets`/`set_array` so both fill and
    white outline disappear. §空間分布 prose updated.
  - Verified: numeric (alignment + suppression counts), synthetic render,
    and real-data render via `report monthly --period 2026-04 --render`.
- **Remaining polish (low priority):** the threshold is now equal in both
  products but defined in each qmd. ADR 0013's "defined once / single
  pipeline path" ideal would factor the suppression into a shared
  `_hex_grid` helper imported by both reports. Mechanisms differ (QC: C is
  per-station so mincnt=stations; CLAS: epoch-pool needs the distinct
  count pass), so a shared helper would need to cover both shapes.

---

## [2026-06-07] Task: Operational scheduling — nightly catchup (daily + N backfill)

### Goal
Start steady-state operation: a nightly launchd job that always runs the
current `daily` (today − lag), then, with spare capacity, backfills up to
N still-incomplete historical days. Keeps "today" current while catching
up history.

### Phase Guard
[ ] Phase 0 — operational scheduling of existing daily/backfill machinery.

### Design
- New `orchestration/catchup.py`: `run_catchup(today, *, lag_days,
  backfill_start, backfill_days, order, ...)`:
  1. target = today − lag_days; `run_day(target)` (the daily — always).
  2. gaps = [d in backfill_start .. target−1 if not is_day_complete(d)];
     order newest-first (default) or oldest-first; take first N.
  3. `run_day(d)` for each gap day; collect results.
  Gap detection via `is_day_complete` → no cursor file, self-healing
  (partials naturally re-targeted), idempotent.
- Optional `--max-hours` deadline guard: always finish the daily, then
  backfill only while under the wall-clock budget (so it never bleeds
  into the workday on slow-FTP nights).
- CLI `pntmoni-pipeline catchup` (top-level).
- `scripts/run_catchup.sh` (caffeinate + .gsi/.env) and launchd plist
  `com.pntmoni.catchup.plist` (replaces/augments the daily plist).
- Tests: gap selection (skips complete, picks N, order), deadline stop,
  daily-always-runs.

### To confirm before coding (config)
- Backfill scope (how far back), N per night, order.

### Done Criteria
- `catchup` runs daily + N gap days; re-runnable/idempotent; launchd
  installed; tests green.

## [2026-07-03] Design: monochrome-ledger visual system (monthly_free)

Source: temp/design_handoff_pntmoni_report (README + pntmoni-v2.scss).
Direction "3a モノクローム台帳" — near-monochrome, hairline rules,
green (#059669) as a single small square marker only, zero radius.

### Phase Guard
[ ] Phase 0 — Quarto report styling; no new scope.

### Plan
[x] Rewrite reports/styles/pntmoni.scss to the v2 token+rule system
    - ink-* scale primary; $slate-* kept as aliases (dashboard-safe)
    - h1 serif cover title; h2 = mono small-caps ledger label + 1px rule
    - tables Tufte hairline (no header shading, no hover)
    - green = marker-only; radius 0 everywhere
    - figures hairline border (no shadow)
    - port tier-gate / data-provenance / independence / document-control
[x] ADAPT callouts to Quarto native DOM (do NOT copy v2 ::before
    content — Quarto auto-renders callout titles; would duplicate).
    Needed `!important` + `.callout.callout-style-*` specificity to
    beat Quarto's own callout CSS (loads after the theme) — otherwise
    the blue/orange left bars + box borders survived.
[x] Renamed the accent marker class `.mark` -> `.accent-mark` (Bootstrap
    owns `.mark` and paints a highlight bg that fought the green square).
[x] Add Source Serif 4 + Noto Serif JP to reports/_brand.yml (cover h1);
    bumped JetBrains Mono to include weight 600 (h2 label weight).
[x] Rendered monthly_free (en, synthetic) + a component design-check
    page; screenshotted via headless Chrome and verified visually.

### Notes / follow-ups
- monthly_free.qmd needed NO structural edits — it uses only native
  Quarto constructs (##/callouts/tables), so the shared SCSS drives it.
- pntmoni.scss is shared, so monthly_qc inherits the same monochrome
  system automatically (intended direction; verify its figures later).
- Green-square accent marker is available as `[value]{.accent-mark}`
  but not yet placed in any template — wire into the headline Fix-rate
  cell when desired.
