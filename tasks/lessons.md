# Pipeline Lessons Learned

This file accumulates pipeline-specific lessons. Cross-cutting
lessons that apply to multiple repositories should be promoted to
`pntmoni-docs/50-operations/` (see ADR 0002 "Lessons sharing").

Format:

```markdown
## [YYYY-MM-DD] <category>: <short title>

**Mistake:** What went wrong.
**Root cause:** Why it happened.
**Fix applied:** What was done.
**Rule:** One-line rule to prevent recurrence.
**Tags:** #python #claslib #mrtklib #quarto #parquet #cost #uv
```

Tags help filter relevant lessons at the start of a session. Read
all lessons tagged for your current work domain before starting.

If a lesson is violated twice: escalate its rule into
`pntmoni-pipeline/CLAUDE.md` Core Principles or promote to
`pntmoni-docs/50-operations/` for cross-repo visibility.

---

## [2026-05-09] python: `.netrc` permission requirement

**Mistake:** First CDDIS BRDC fetch failed with `NetrcParseError: ~/.netrc
access too permissive`.
**Root cause:** Python's stdlib `netrc` module enforces 0600 on
`~/.netrc` (owner-only). Default umask had left it at 0644.
**Fix applied:** `chmod 600 ~/.netrc`.
**Rule:** Any Python tool that reads `.netrc` (httpx, requests,
stdlib `netrc`) requires 0600. Document this in setup instructions.
**Tags:** #python #cddis #earthdata #setup

---

## [2026-05-09] python: httpx strips `Authorization` on cross-origin redirect

**Mistake:** CDDIS BRDC fetch silently saved the URS login HTML page
(11 KB) as if it were the gzipped NAV file (~1.3 MB). HTML guard
caught it on retry but only after wasted bandwidth.
**Root cause:** httpx (matching browser/`requests` security defaults)
strips the `Authorization` header when following a redirect to a
different origin. CDDIS issues a 302 from `cddis.nasa.gov` to
`urs.earthdata.nasa.gov/oauth/authorize`, so Basic Auth never
reaches URS and the auth flow stalls on the login HTML form.
Even setting `auth=` on `httpx.Client(...)` does not bypass the
cross-origin strip.
**Fix applied:** Replaced top-level `httpx.stream()` with manual
redirect handling in [`_http.py`](../src/pntmoni_pipeline/acquisition/_http.py).
A single `httpx.Client(follow_redirects=False)` walks the redirect
chain and applies Basic Auth only when the next hop's host is in
`auth_hosts` (e.g. `EARTHDATA_AUTH_HOSTS={"urs.earthdata.nasa.gov"}`).
Cookies persist on the same client. Added an `_looks_like_html()`
guard that rejects HTML payloads when `expect_binary=True` (default).
**Rule:** Whenever an HTTP source uses cross-origin OAuth (URS,
ECMWF MARS, ESGF, etc.), use the `download(..., auth_hosts=...)`
selector. Never trust `follow_redirects=True` to carry Basic Auth
across hosts. Always validate downloaded content type/size.
**Tags:** #python #httpx #cddis #earthdata #oauth #auth

---

## [2026-05-09] data: GEONET F5 station IDs are 6-char, not 4-char

**Mistake:** Considered using `filter_by_prefix` with 4-char GEONET
station IDs (e.g. `0231`) to select F5 files, but F5 filenames
follow a different scheme — e.g. `000842.26.pos`, `00R015.26.pos`.
**Root cause:** GSI uses 6-character codes for F5 coordinate files
(legacy F-numbered station codes), distinct from the 4-character
RINEX archive identifiers.
**Fix applied:** Documented in this lesson; full-mirror default in
[`geonet_f5.fetch`](../src/pntmoni_pipeline/acquisition/geonet_f5.py)
works fine. If/when station-level F5 selection is needed, the prefix
must be the 6-char form.
**Rule:** Never assume station-ID schemes are uniform across GSI
products. RINEX (`GRJE_3.02`) uses 4-char IDs; F5
(`coordinates_F5/GPS`) uses 6-char IDs; F3 (`coordinates_F3`) may
differ again. Verify with NLST before building filters.
**Tags:** #geonet #gsi #data-conventions

---

## [2026-05-09] build: CLASLIB rnx2rtkp does not build cleanly on macOS clang

**Mistake:** First attempt at `make -C vendor/pntmoni-claslib/util/rnx2rtkp`
failed with `error: call to undeclared function 'strtok_r'` from
`rtkcmn.c:3514`.
**Root cause:** Two compounding issues:
1. The Makefile passes `-ansi -pedantic` (i.e. `-std=c89 -pedantic`),
   which prevents declaration of POSIX functions like `strtok_r`.
2. `src/rtkcmn.c:113` defines `_POSIX_C_SOURCE 199309` (POSIX.1b-1993,
   pre-`strtok_r`) — this in-file `#define` overrides any cmdline
   `-D_POSIX_C_SOURCE=200809L`. Apple clang 21 promotes
   implicit-function-declaration to error by default, so the build fails.
   The file has CRLF line endings (Windows-style), which made
   one-shot `sed -i 's|...$|...|'` replacements no-op.
**Fix applied (verification only):** Locally edited
`vendor/pntmoni-claslib/src/rtkcmn.c` to bump `_POSIX_C_SOURCE` to
`200809L`, then bypassed the Makefile by calling `gcc` directly with
the source list extracted from the Makefile's `SRCS`/`RCV_SRCS`
variables. Built without `-DLAPACK` (used the Makefile's commented
"without lapack" path) — slower for large-N but adequate for
verification.
**Rule:** Track these as candidate fork-side modifications:
- **MOD-NNN (build hygiene)**: bump `_POSIX_C_SOURCE` to `200809L`
  in `rtkcmn.c`; either drop `-ansi` from the Makefile or add
  `-D_DARWIN_C_SOURCE` for macOS portability.
- **MOD-NNN (LAPACK)**: switch the Makefile's macOS branch to use
  `-framework Accelerate` instead of `-llapack -lblas` so production
  builds get hardware LAPACK/BLAS without Homebrew dependency.
Until those land, the build recipe lives in this repo's
`tasks/lessons.md` and `tasks/todo.md`. The local working-tree edits
make the submodule "dirty"; `git describe --tags --dirty` reports
`v0.8.3-pntmoni-1-dirty` and that string is now captured as
`engine_version` in `processing.jsonl` — exactly the audit signal we
want.
**Tags:** #build #claslib #macos #pntmoni-claslib #mod-candidates

---

## [2026-05-09] data: kinematic_p30.conf references newer aux data than CLASLIB ships

**Mistake:** First processing run failed (or would have, before being
caught) because `kinematic_p30.conf` references
`data/igs20.atx` and `data/clas_grid_003.def`, neither of which
ship with CLASLIB v0.8.3 (`data/igs14_L5copy.atx` and
`data/clas_grid.def` are the available versions).
**Root cause:** The production config was authored against a newer
aux data drop than is present in `vendor/pntmoni-claslib/data/`.
The newer files (igs20 antex with full Galileo/BeiDou PCV;
clas_grid_003.def with 2024 grid update) need to be sourced
externally — they are not redistributable through CLASLIB.
**Fix applied:** Created `configs/kinematic_p30_verify.conf` that
points at the CLASLIB-shipped versions for first-run verification.
Production `kinematic_p30.conf` is untouched so the upgrade path is
trivial (drop newer files into a local data dir + use the original
config).
**Rule:** When adding a new mode config, audit `file-*` references
against the actual aux data dir (`vendor/pntmoni-claslib/data/`)
before first run. If newer files are required, surface that as a
setup task and either (a) provide the verify variant, or (b) stage
the newer files in a writable overlay and point `--data-dir` at it.
The verify run produced 96% Q=4 (RTK FIX, ambiguity-resolved) on
station 0231 even with the older atx, so the verify config is good
enough for end-to-end pipeline validation. Whether the newer
`igs20.atx` materially improves fixing rate or accuracy is a
separate measurement worth doing once that aux data is staged.
**Tags:** #claslib #aux-data #setup

---

## [2026-05-09] data: 2026-04-01 reference is verify-grade (trailing 7 days)

**Mistake / context:** Stage-1 `epoch_errors`, Stage-2a `accuracy`,
and Stage-2b `ttff_stats` Parquets for **2026-04-01** were generated
against `data/processed/reference_coords/2026/20260401.parquet`,
which used only 7/15 days (all 2026-03-25 to 2026-03-31, ALL
pre-target). The F5 publication snapshot acquired 2026-04-02 ends at
2026-03-31 — the 8 post-target days the ±7 d window expects (2026-04-01
to 2026-04-08) had not been published yet. Because the original
`min_fixed_days` default was 7, the partial-window run silently
proceeded.
**Root cause:** Default `min_fixed_days=7` was too permissive for a
"is this production-grade?" gate. F5 has a structural ~1 month
publication delay; any target within the most recent ~5 weeks will
necessarily have a partial window.
**Fix applied:**
- Bumped `_reference_coords.DEFAULT_MIN_FIXED_DAYS` from 7 → 14
  (admits at most one jump-NaN'd day in a 15-day ±7 window)
- Added CLI `--min-fixed-days` flag for explicit override
- `--allow-partial-window` is now the only way to accept partial-
  publication windows; without it the run fails loudly
**Implications for the 2026-04-01 verify run:**
- The reference is "trailing 7-day median ending 2026-03-31".
- Secular bias from tectonic motion: ~3 cm/year × 1 week ≈ <1 mm
  (negligible).
- Random noise: 7-day median has ~1.46× the standard error of a
  15-day median; F5 daily noise is sub-cm so the additional noise
  is ~mm-level — visible but not large.
- No earthquake / jump events in the window (gsi_jumps.toml is empty,
  no GSI announcements during 2026-03-25 to 2026-04-08).
- Verdict: **OK for pipeline verification, NOT production-grade**.
  Re-run reference_coords + epoch_errors + accuracy + ttff_stats +
  monthly after 2026-05 mid (when F5 publication catches up to the
  ±7 d window for early April).
**Rule:** Production gating defaults must be strict enough that
"silently proceed in degraded mode" is not the default behaviour.
When external publication has structural delay, fail-loud + opt-in
is the right posture; opt-in must produce loud provenance signals
(``n_fixed_days_used`` is recorded — the gate must read it).
**Tags:** #reference-coords #f5 #publication-delay #verify-grade

---

## [2026-05-09] migration: legacy clas_eval CSVs → station registry TOMLs

**Mistake / context:** First pass of `migrate_legacy_station_data.py`
produced incomplete output for two reasons.
**Root causes:**
1. **fy2021_1st_h.csv has a leading blank line before its header.**
   `csv.DictReader` treated the empty line as the header (fieldnames =
   `['']`), so all rows were misread and the file appeared to contain
   zero stations. Result: every eval station looked like it had a gap
   in fy2021_1st_h.
2. **station_network_info.csv contains `nan` strings for stations that
   have fewer than 4 corrective grids.** `int(float("nan"))` raises;
   guard added.
**Fix applied:** `_open_csv_skip_blank_header` strips leading blank
lines before passing to DictReader; `_parse_optional_int` treats
`"nan"` as None; the network_info loader skips grid slots with
non-finite numerics.
**Result:** 9/9 fy_h files contribute 72–78 rows each; 75 unique eval
stations across 2020-Q4 → 2024-Q4. 69 stations have all 9 periods
(the long-tenured set); 3 stations (0618, 0810, 0969) have genuine
multi-period sequences with internal gaps — exactly the
"earthquake-removed-then-restored" pattern the user described.
**Rule:** Always peek at byte-level structure (`xxd | head`) of new
legacy CSVs before trusting `csv.DictReader`. Stray newlines, BOMs,
NaN string sentinels, and trailing footer rows are all silent failure
modes. Log the row count per source file so corruption is
immediately visible at INFO level.
**Tags:** #migration #legacy #csv #data-hygiene

---

## [2026-05-09] audit: 29 eval stations marked `isinside=False` in 2025 station_ng

**Finding** (not a bug): 29 GEONET stations appear in
`service_performance/fy*_*_h.csv` (i.e. they ARE QSS official CLAS
evaluation points at some past fiscal half) but the most recent
`station_ng.csv` (2025) marks them `isinside=False`. Examples include
`0500` (netid=1), `0007` (netid=10), `0011` (netid=11).
**Most likely explanation:** `isinside` in `station_ng.csv` is
computed by a stricter criterion than "any CLAS network has any grid
near this station" — possibly a coverage polygon or a per-network
boundary check that has tightened since some of these stations were
first evaluated. Each of these stations has a valid `netid`, so they
*are* assigned to a CLAS network; the `isinside` flag is a separate,
narrower test.
**Implications for the qualification layer (tracked separately):**
- Treat `eval_periods.toml` as authoritative for "is this station an
  official evaluation point at date D?"
- Treat `network_assignments.toml::isinside` as a secondary signal
  about coverage geometry, not as a gate on the eval set
- The qualification mechanism (Backlog #2 + Phase 0–1 task) should
  document both signals and let monthly-report criteria choose
**Rule:** When two legacy data sources disagree about a flag's
meaning, do not silently reconcile during migration. Preserve both,
log the discrepancy count, and defer reconciliation to the explicit
qualification step that can record its choice in the methodology
document.
**Tags:** #registry #qualification #legacy-data #audit

---

## [2026-05-09] design: reference coordinates via per-day Common-Mode Removal

**Mistake / context:** The reference toolbox's `make_coord.py` computes
station truth coords by subtracting the *median* fixed-station coord
(a constant) from each day's published station coord, then taking
nanmedian. That is not strictly Common-Mode Removal — common-mode
drift remains in each day's value, and only median robustness saves
the result.
**Root cause / corrected understanding:** GSI's F5 solves all stations
*relative* to the network anchor (Tsukuba1, F5 ID 92110). When IGS
products have gaps, the fixed station's absolute coordinate jumps,
and **all other stations' published coordinates jump together by the
same amount** (because F5 anchors them to Tsukuba1). So the per-day
relative ``station_xyz_i − fixed_xyz_i`` is invariant across jumps.
**Fix applied:** Implemented per-day relative (Method B) instead of
median-centering (Method A). Algorithm:
- ``fixed_truth = nanmedian(fixed_xyz_in_window with jump days NaN'd)``
- ``relative_per_day = station_xyz_i − fixed_xyz_i`` (no NaN unless
  data missing — relative is invariant across jumps)
- ``station_truth = nanmedian(relative_per_day) + fixed_truth``
Jump filtering applies ONLY to the fixed station (per the GSI/F5
design). Non-fixed stations have no jump filter — relative is
already invariant.
**Rule:** When relative-positioning frames are stable but absolute
frames have known glitches, use per-day relative for downstream
metrics rather than median-centered absolute. Don't rely on median
robustness when the structure of the data lets you cancel the noise
deterministically.
**Tags:** #reference-coords #f5 #cmr #methodology

---

## [2026-05-09] data: F5 publication delay is structural

**Mistake / context:** First reference-coord run for 2026-04-01
returned a window of 7/15 fixed days because F5's 2026 archive
(snapshot taken 2026-05-09) only covered through 2026-03-31.
**Root cause:** GSI publishes F5 in weekly batches with a structural
~1-month delay. For target date T, F5 covering [T, T+7d] becomes
available roughly T+30 days later.
**Fix applied:** Reference-coord computation accepts a
``--allow-partial-window`` flag and a ``min_fixed_days`` threshold
(default 7) so partial windows are explicit failures rather than
silent. The provenance JSONL captures ``n_fixed_days_used`` so
downstream consumers can see which days were available. For monthly
reports, run reference_coords AFTER F5 catches up (typically the
month following the target month).
**Rule:** Whenever an external publication has a structural delay,
make the delay explicit in CLI behaviour: fail loudly by default,
require an opt-in flag for partial data, record the realised
coverage in provenance. Do not paper over the delay with
"best-effort silently shifted window" semantics — that hides the
real-world data dependency from operators.
**Tags:** #f5 #publication-delay #provenance

---

## [2026-05-09] benchmark: TTFF DOY adds zero overhead vs non-TTFF

**Mistake / context:** Concern that adding `misc-regularly = 900` (15-min
periodic filter reset, ADR 0005 primary period) on top of LAPACK build
might significantly extend wall time. We need TTFF for the monthly
report, but not at the expense of monthly batch budget.
**Result:** Same DOY (2026-04-01, 1298 stations, LAPACK + Accelerate):
- Without TTFF: 42.7 min wall, p50=19.7s, p95=21.3s
- With TTFF (misc-regularly=900): **41.85 min** wall, p50=19.4s, p95=21.1s
- Difference is within measurement noise (≤2%); resets zero out
  filter state but don't add per-epoch compute
**TTFF metric (1298 stations × 96 windows = 124,608 samples)**:
- Median per-station TTFF p50: **180 s (3 minutes)**
- Median per-station TTFF p95: 300 s (5 minutes)
- Raw mean fix-success-rate: 94.26%; excluding 0-fix outliers
  (1098, 1140): 94.40%
- 1297/1298 stations have at least one fixed window
**Rule:** TTFF processing can run on the full GEONET network within
the same monthly-batch budget as the non-TTFF baseline. No need to
separate the workflows. Dual-period strategy (ADR 0005: 900 s primary,
3600 s secondary in Phase 1) remains feasible — running both periods
sequentially would still complete in ~1.4 h/day, ~42 h/month wall.
**Tags:** #benchmark #ttff #ppp-rtk #performance #adr-0005

---

## [2026-05-09] bug: TTFF analyzer drifted on .pos files with observation gaps

**Mistake:** First TTFF aggregator reported `ttff_p50 = 0 s` for 4
stations (0085, 0285, 0454, P218) — meaning the median window appeared
to fix on its very first epoch. That can't happen physically when
``misc-regularly`` resets the filter at each window start.
**Root cause:** First implementation of `extract_events` assumed
`epoch_idx == file_line_index`, i.e. that the .pos contains exactly
one entry per `ti` second from the start of the run. In reality some
GEONET stations have observation gaps, so .pos files can be 1987–2879
lines (vs the full 2880). With CLASLIB's MOD-001 fix triggering resets
on TOW-modulo (not file position), my line-based windowing drifts away
from the actual reset boundaries — windows can land in the middle of
the next reconvergence sequence, where Q=4 is already established.
**Fix applied:** Replaced `parse_pos_quality` (line-ordered list) with
`parse_pos_epochs` (NMEA UTC → GPST seconds-of-day → `epoch_idx //
ti` map). `extract_events` now operates on a sparse `dict[int, int]`
and accepts an explicit `n_windows` (= 86400 / R for a full day) so
trailing missing windows are still reported as unfixed. Added gap-
handling unit tests (`test_extract_events_dict_with_gap_does_not_drift`,
`test_parse_pos_epochs_aligns_to_gpst_day`,
`test_parse_pos_epochs_handles_observation_gap`). Re-ran on the
existing .pos files (no re-processing needed): 0085, 0454 etc. now
report sensible p50=180s. `n_observed_epochs` is now part of the
ttff.jsonl metadata so future qualification criteria can filter on
data completeness directly.
**Rule:** When a metric depends on a time-aligned reset, never
collapse "epoch index in time" with "line index in file". Always
align via GPST/TOW. Watch for any metric that produces 0 or other
edge values when the answer should be non-zero — that's a strong
signal of an off-by-N alignment bug. Validate aggregators on at
least one station with known observation gaps before publishing
numbers.
**Tags:** #ttff #bug #alignment #observation-gaps

---

## [2026-05-09] design: CLAS evaluation qualification belongs at aggregation, not processing

**Mistake / context:** While reviewing why stations 1098 and 1140
report 100% Q=1 (single point), proposed adding a
`configs/stations/excluded.toml` that the processing layer would honour
to skip these stations. User flagged that this is the wrong shape: in
the previous toolbox, station qualification was handled at the
**aggregation** stage based on observation-quality criteria, not by
hardcoded exclusion at processing.
**Root cause:** "Skip at processing" loses raw evidence and bakes in
a subjective coverage assumption. "Filter at aggregation" preserves
all .pos files, lets multiple criteria be applied to the same data
without re-processing, and matches PNT Moni's transparency/audit
posture (raw outputs available; criteria explicit in the report).
**Fix applied:** Did NOT add `configs/stations/excluded.toml`. Added
[tasks/todo.md](tasks/todo.md) item: "Station qualification +
dual-aggregate (raw + qualified)". Stations 1098 (Minamitorishima)
and 1140 (Okinotorishima) — confirmed via F5 J_NAME — are CLAS
out-of-coverage Pacific remote islands and will be excluded by a
future `qualification` step using observation-quality + coverage
criteria, applied at the analysis layer.
**Rule:** When a station looks like an outlier, do not hardcode an
exclusion. Document the cause, defer to a `analysis/qualification`
component (planned), and report aggregates twice: "raw N stations"
+ "qualified subset N' stations meeting criteria X, Y, Z". This
keeps the methodology auditable and reusable.
**Tags:** #methodology #qualification #design #transparency

---

## [2026-05-09] benchmark: LAPACK (Apple Accelerate) cuts DOY wall time by ~30%

**Mistake / context:** First full-DOY benchmark used CLASLIB's internal
matrix routines (no `-DLAPACK`). The added TTFF processing planned for
Phase 0 will increase per-station compute, so we wanted production
headroom.
**Result:** Rebuilt rnx2rtkp with `-DLAPACK` linked against Apple
Accelerate framework via [scripts/build_claslib.sh](../scripts/build_claslib.sh).
Re-ran the same DOY 091 / kinematic_p30_verify on identical inputs.
- Wall time: **42.7 min vs 55.2 min** (1.29× speedup)
- Per-station p50: **19.7 s vs 25.4 s** (1.29×)
- Per-station p95: **21.3 s vs 29.1 s** (1.37× — bigger improvement
  on the slower stations; suggests their bottleneck was matrix work)
- Global PPP-RTK active rate (Q=4 + Q=5): **99.63% in both builds**
  (perfect agreement on whether PPP-RTK converged)
- Global FIX rate (Q=4): 92.95% (LAPACK) vs 93.24% (no-LAPACK) —
  0.29 percentage point shift between FIX and FLOAT, expected
  numerical-precision noise across LAPACK implementations
- Q=1 (single-point) rate identical: 0.37% (limited to 2 stations
  — `1098`, `1140` — that fall back regardless of build, so this
  is a station-specific data issue not a LAPACK regression)
**Implications:**
- Monthly batch projection drops from ~28 h/month to ~21 h/month
- p95 headroom of ~8 s/station available for adding TTFF processing
- LAPACK should be the default production build
**Rule:** Always build with `-DLAPACK + Accelerate` on macOS for
production runs (`scripts/build_claslib.sh` defaults to this). The
no-LAPACK path remains for debugging via `--no-lapack`. When
benchmarking changes, isolate variables: do not change LAPACK and
config simultaneously between two runs.
**Tags:** #benchmark #lapack #accelerate #performance #macos

---

## [2026-05-09] data: two GEONET stations fall to Q=1 regardless of build

**Mistake / context:** While reviewing FIX-rate distribution after
the LAPACK build, found stations `1098` and `1140` reporting 0% Q=4
and 100% Q=1 across all 2880 epochs of DOY 091.
**Root cause:** Confirmed by re-checking the no-LAPACK output for
the same stations — both show 100% Q=1 there too. The PPP-RTK
filter never converges on these stations on this DOY. Likely
causes (untested): CLAS network-cluster coverage gap, antenna/
receiver mismatch unhandled by config, or an OBS data quality
issue specific to these stations on this date.
**Fix applied:** None yet — this is a finding, not a regression.
Documented as a known outlier so the global FIX-rate metric is not
mistaken for a per-station guarantee.
**Rule:** When summarising a DOY's FIX rate, report both the global
percentage AND the count of stations with anomalously low FIX rate
(threshold to be tuned, e.g. <50%). Single-station outliers should
not skew the global narrative, but they should be tracked for
follow-up. If the same stations repeat across multiple DOYs, escalate
into an investigation task.
**Tags:** #claslib #ppp-rtk #data-quality #geonet

---

## [2026-05-09] benchmark: first full-DOY processing on 2026-04-01

**Mistake / context:** First-ever full-DOY (1298-station) CLASLIB
processing run on PNT Moni's hardware. We did not have an a priori
estimate of monthly-batch wall time, only Phase 0's "≤8 hours/month
operational budget" target.
**Result:** With `pntmoni-claslib v0.8.3-pntmoni-1` (MOD-001 applied),
no LAPACK, 30 s sampling, ppp-rtk + l1+l2+l5, 10-core
ThreadPoolExecutor:
- Wall time: **55.2 min for 1 day / 1298 stations** (kinematic_p30_verify)
- Per-station: p50 = 25.4 s, p95 = 29.1 s
- Σ duration / wall = 10.0× (perfect parallelism, no I/O contention)
- Failures: 0
- Mean Q=4 (FIX) rate across a 30-station sample: 93.9%
  (range 76.6%–99.1%); Q=2 rate: 0% (never degrades to DGPS)
- Output: ~516 KB/.pos × 1298 = 669 MB / DOY
**Implications for monthly batch:**
- 30 days × 55 min ≈ **27.6 hours/month** wall, well inside the
  founder workload budget (≤80 h/month)
- Disk: 669 MB × 30 ≈ 20 GB/month for .pos NMEA; smaller once
  converted to Parquet (planned)
- A LAPACK-enabled rebuild would likely cut per-station time
  substantially (untested) — meaningful margin to absorb future
  MRTKLIB-parallel evaluation (ADR 0001)
**Rule:** Re-measure this baseline whenever any of the following
changes: CLASLIB fork rebase, new `MOD-NNN`, OS/clang upgrade,
LAPACK enable/disable. The trend is captured automatically in
`data/metadata/processing.jsonl` (Tier 2). If wall time exceeds
~3× the baseline (165 min) for a non-throttled run, treat as a
silent regression and investigate before merging the change.
**Tags:** #benchmark #claslib #ppp-rtk #performance #monthly-batch

---

## [2026-05-09] interpretation: NMEA GGA quality flag in CLASLIB

**Mistake:** First read of `outnmea_gga` output for station 0231
inverted the meaning of Q=4 vs Q=5; reported the run as "96% RTK
float" when it was actually "96% RTK FIX".
**Root cause:** Confused the `SOLQ_*` enum order in `rtklib.h`
(SOLQ_FIX=1, SOLQ_FLOAT=2) with the NMEA-quality field. The
mapping is performed by `solq_nmea[]` in `solution.c:56-62`, which
follows NMEA 0183: index 4 = RTK fixed, index 5 = RTK float.
**Fix applied:** Corrected the run analysis. The verify-mode run
produced 96% Q=4 (FIX) — a good result, not a poor one.
**Rule:** When interpreting CLASLIB NMEA output, use NMEA 0183
conventions: Q=1 single, Q=2 DGPS, Q=4 RTK fixed, Q=5 RTK float.
Cross-reference `solq_nmea[]` in `solution.c` rather than reading
the SOLQ enum directly. When summarising a run for the user,
double-check the value-to-meaning mapping before reporting
percentages — inversions are easy and embarrassing.
**Tags:** #claslib #nmea #interpretation #ppp-rtk

---

## [2026-05-09] design: provenance JSONL is append-only attempt log

**Mistake:** After a failed BRDC download saved an HTML file as if
it were the real artifact, the JSONL provenance log retained the
failed entry alongside the successful retry — so the same `path`
appeared twice with different `sha256` and `size_bytes`.
**Root cause:** [`_provenance.record`](../src/pntmoni_pipeline/acquisition/_provenance.py)
appends every result, including ones written by an earlier-buggy
code path that didn't validate content. Subsequent runs do not
de-dup or supersede prior entries.
**Fix applied:** Documented the semantics: the JSONL is an audit
log of *attempts* recorded at the time they happened. Consumers
that need "current truth per path" must pick the latest entry per
`path` and verify the file still exists.
**Rule:** Treat `acquisition.jsonl` as immutable history. When the
report renderer or downstream consumers want the canonical record
per artifact, query `latest-by-path-where-file-exists`, not
`first-match-by-url`.
**Tags:** #provenance #design #data-engineering
