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
**Followup (2026-05-16):** When extracting the CLAS 72 evaluation
points from the QSS Service Performance Report PDF, station IDs are
written in the 6-digit F5 form (e.g. ``950500``) — convert to the
4-char RINEX form by taking the **last 4 characters**. Same rule
handles 5-digit edge cases (``93001`` → ``3001``). Verified against
``configs/stations/eval_periods.toml`` cross-reference.
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

## [2026-05-10] reference: F5 → F5.1 switchover effective 2026-04-01

**Context**: QSS announcement
[IS-QZSS_260327](https://qzss.go.jp/info/information/is-qzss_260327.html)
fixes the CLAS evaluation reference's switch from F5 (ITRF2014) to
F5.1 (ITRF2020) at **2026-04-01 JST** (backup date 2026-04-02). Both
archives remain published; the switch is methodological, not access.
**Implementation**: ``acquisition.geonet_f5.CLAS_F51_EFFECTIVE_DATE``
codifies the date and ``variant_for_date(target)`` returns the
official variant for a given date. CLI ``analyze reference-coords
--f5-variant auto`` (now the default) auto-resolves per target; runs
that span the switch (e.g. ``--week 2026-W14`` covering 2026-03-30 to
04-05) raise an error asking the operator to split into two runs.
**Boundary edge case 2026-03-25 to 2026-03-31**: pre-switch dates
whose ±7 d window extends into post-switch days. F5 publication may
freeze at 2026-03-31; the official methodology is to evaluate these
dates against F5 with whatever days are available. PNT Moni mirrors
this — operators must pass ``--allow-partial-window`` for these
boundary dates and document the days-used count from provenance.
**Rule**: When an upstream methodological switch is anchored to a
calendar date, codify the date as a constant (not a string in
docstrings) and add an auto-routing layer at the CLI so individual
runs cannot pick the wrong variant by accident. The spanning case
fails loudly because the most common "natural" mistake is to roll up
a week that straddles the switch.
**Tags:** #f5 #f5_1 #clas #switchover #adr-0001

---

## [2026-05-10] data: igs20.atx is officially adopted; igs14_L5copy is content-equivalent

**Context**: As of the F5→F5.1 switch (2026-04-01) the official IGS
antenna PCV file is ``igs20.atx``. CLASLIB ships
``igs14_L5copy.atx``, whose contents are equivalent to igs20.atx
(per user verification — same per-block antenna offsets/PCVs).
**Status**:
- ``configs/kinematic_p30_verify.conf`` continues to reference
  ``data/igs14_L5copy.atx`` for verify runs against the CLASLIB-
  shipped ``data/`` dir. Functionally equivalent to igs20 today.
- ``configs/kinematic_p30.conf`` (production) references
  ``data/igs20.atx`` directly. The production aux-data dir is not
  yet staged in this repo (tracked in tasks/todo.md).
**Rule**: Don't silently swap content-equivalent ANTEX files at the
filename layer; downstream provenance loses the trail. When the
production aux-data dir lands, the file should be the official
``igs20.atx`` from
``https://files.igs.org/pub/station/general/igs20.atx`` with sha256
recorded in provenance.
**Tags:** #igs #antenna-pcv #aux-data

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

## [2026-05-16] satellite_outages: NAQU L6 outages do NOT imply CLAS unavailable (4-way redundancy)

**Mistake / context:** First normalisation pass mapped any QZSS NAQU
with ``NAQ_SS_SIGNAL = L6`` to an ``affected_signals = ["L6"]`` event,
implying "if L6 is out, CLAS is out". Live NAQU 2025 data showed
157 L6-band outages across the four QZS satellites (SVN2: 24,
SVN3: 41, SVN4: 42, SVN5: 50). At face value this would suggest
CLAS was unavailable hundreds of times in 2025 — wildly contradicted
by the QSS Service Performance Report which shows ≥99 % CLAS
service availability.
**Root cause:** The CLAS service rides on the **L6D** message
stream, which is broadcast redundantly from ALL FOUR operational
QZS satellites (per Performance Report Table 5: SVN002/003/004/005
each with a distinct PRN). A single satellite's L6-band outage
removes one broadcaster but the remaining three continue carrying
L6D, so the user-side CLAS service remains available. CLAS service
becomes unavailable only when the receiver's visible CLAS-broadcasting
QZS set drops to zero — a function of (a) all broadcasters
simultaneously down, or (b) local-sky geometry that has no
CLAS-broadcasting QZS above the elevation mask.
**Fix applied:** No code change required at the producer layer — the
raw notice records and the OutageEvent schema already capture per-SVN
L6 outage windows. What changed is the **interpretation rule** for
downstream consumers, documented in
[``pntmoni-docs/40-data-schemas/satellite-outages.md``](../../pntmoni-docs/40-data-schemas/satellite-outages.md)
and in this lesson:

- "L6 outage on a single SVN" ≠ "CLAS unavailable"
- "CLAS unavailable" must be computed by intersecting outage windows
  across the CLAS-broadcasting SVN set, OR by checking for explicit
  CLAS-service-down notices (NAQU subtypes carrying signal=CLAS or
  service-level outage prefixes)

A helper (``analysis/clas_availability.py`` planned) will encapsulate
this calculation so monthly-report consumers don't reproduce the
mistake. Tracked in ``tasks/todo.md`` as a v2 task.
**Rule:** When a service is broadcast redundantly across multiple
sources, treat per-source outages as **inputs** to a service-availability
calculation — never as the calculation itself. Bake the redundancy
topology into a dedicated helper module so consumer code can't make
the "one source down = service down" mistake by accident. Encode
the topology (broadcaster set, PRN assignments) explicitly somewhere
auditable, not as folklore.
**Tags:** #satellite-outages #clas #naqu #qzss #redundancy #methodology

---

## [2026-05-16] http: httpx requires dict-form POST data, not list-of-tuples

**Mistake:** First NAQU acquisition run failed instantly with
``TypeError: sequence item 1: expected a bytes-like object, tuple
found`` inside ``h11._connection.send``. The form-data was passed as
a ``list[tuple[str, str]]`` to ``httpx.Client.post(data=...)`` —
visually familiar from ``urllib.parse.urlencode`` which accepts
tuple-lists for repeated keys.
**Root cause:** httpx's ``data=`` argument expects a
``Mapping[str, str | list[str]]``, not a sequence of tuples. The
list-of-tuples form is accepted by stdlib's urllib but produces a
malformed encoding chain inside httpx → h11, surfacing as a
type error during the byte-join in the connection layer rather
than at the API boundary where it could be reported clearly.
**Fix applied:** Changed ``naqu._query_page`` to build a ``dict``,
unpacking the constant flag tuples via ``dict(_DEFAULT_SERVICE_FLAGS)``.
All values stringified explicitly. NAQU 2025 fetch then completed in
1.7 s (568 records).
**Rule:** When passing form data to httpx, always use a dict. Reserve
list-of-tuples for stdlib's ``urllib.parse.urlencode`` (which builds a
string) — not for httpx's data parameter (which expects a mapping).
For repeated keys, use ``dict[str, list[str]]`` (httpx-supported) or
build the urlencoded string explicitly and pass it as
``content=...`` with a manual content-type header.
**Tags:** #httpx #python #web-api #satellite-outages

---

## [2026-05-16] data: GPS NANU "GENERAL" type has different format (no DTG/SVN/sections)

**Mistake / context:** First NANU 2025 enumeration parse-skipped two
notices (2025003, 2025017) with no obvious failure mode in the
parser. On inspection these are NANU type ``GENERAL`` — a different
format from the standard numbered-section grammar that
``_navstar_format.parse`` expects.
**Root cause:** GENERAL NANUs are free-text announcements (e.g.
"On 22 Jan 2025, GPS will transition SVN44 into the broadcast
almanac…"). They lack the structured Section-1 fields (NANU TYPE,
NUMBER, DTG, SVN, PRN, START/STOP JDAY/TIME). The strict parser
requires DTG to construct ``published_at``, so the parse returns
``None`` and the notice is silently skipped.
**Fix applied:** Added an INFO-level log distinguishing GENERAL-type
skips from genuine parse failures. The notice is not stored as a
raw_notice. The full body text is still available from upstream by
re-fetching the URL, so no data loss.
**Rule:** When a parser is strict about fields the upstream
sometimes omits, log the structural reason for the skip
(``"GENERAL type, skipped (no SVN/window)"``) so operators can
distinguish "format we know about but chose not to handle" from
"format we didn't know existed". Document the skipped variants in
the schema doc as known not-currently-handled cases. v2 may stuff
GENERAL into raw_notices with ``fetched_at`` as ``published_at`` and
a sentinel ``notice_type = "GENERAL"``; for v1 the operational
information gain is minor and we keep the data layer strict.
**Tags:** #nanu #parser #data-conventions #satellite-outages

---

## [2026-05-16] methodology: CLAS 72 force-include is load-bearing for coastal/island networks

**Mistake / context:** First sketch of the station qualification scheme
treated the CLAS Official 72 evaluation points as just one signal among
many. User flagged: "気をつけないといけない点としては、clas official評価点
72点を含むようにしないと、網によっては評価点が一点も選ばれなくなることがあります
（主に沖縄と小笠原）". Verified empirically on the Feb-Apr 2026 window:
the 99.73th-percentile QC thresholds (derived across the whole GEONET)
flag essentially every Okinawa / Ogasawara station, because their
tropical / oceanic environments produce multipath and cycle slips well
above continental-Japan medians. Without the force-include overlay,
netid 1 (Ishigaki), 2 (Okinawa central), and 12 (Ogasawara) would
qualify ZERO stations from QC alone.
**Root cause:** A single network-wide 3σ band penalises systematic
environmental difficulty, not per-station deterioration. The QSS
official evaluation set is the methodological escape hatch — those
stations are evaluated *in spite of* harsh environment because the
CLAS service must work there too.
**Fix applied:**
- ``analysis/qualification.qualify()`` overlays the CLAS 72 set (from
  ``eval_periods.toml``) as ``force_eval``. The final rule is
  ``qualified = (qc_pass OR force_eval) AND NOT out_of_service``.
- Force-eval has a fall-back: when no period in the registry covers
  ``ref_date`` (e.g. official report has not yet published the
  current half-year), use the LATEST available period. Matches the
  operational reality that QSS reports lag ~5 months.
- ``configs/stations/out_of_service.toml`` is a hard veto layer for
  stations that should be excluded regardless (e.g. 1098 / 1140 are
  not in CLAS coverage at all; evaluating them would distort metrics).
**Observed (ref_date=2026-04-30, window=90d):** qualified=1083/1300
with 15 force-eval rescues (qc_fail-but-CLAS-72). The 15 rescues
include IRIOMOTEJIMA (0500), IRABU (0747), TARAMA (0748), ISHIGAKI1
(0749), HATERUMAJIMA (0751), MOTOBU (0496), KIKAI2 (0732), SETOUCHI
(0733), YANAI (0414), KAMIYAMA (0557) — exactly the southern-island
cohort the user predicted.
**Rule:** Population-derived QC thresholds describe the global
distribution; they do NOT describe whether a station is operationally
acceptable for the service it backs. When official-evaluation lists
exist, treat them as authoritative force-include — the alternative is
silent geographic blind spots. Document the rescue count in every
qualification provenance record so methodology audits can see how
many stations got the override.
**Tags:** #qualification #methodology #clas #okinawa #ogasawara #force-eval

---

## [2026-05-16] perf: pyarrow per-row column access is ~100µs / call — vectorise to numpy

**Mistake:** First implementation of ``qualification._check_station_day``
looped per station per day per threshold (~120 thresholds × 1298
stations × 89 days ≈ 14M iterations), each calling
``t.column(col)[row_idx].as_py()`` to extract a single float. On the
Feb-Apr 2026 window this exceeded 3 minutes wall and was still going
when killed.
**Root cause:** pyarrow's chunked array indexing involves a
chunk-resolution + Python object boxing on every ``__getitem__`` —
roughly 100 µs per call from Python. The cost is invisible at small
scales (unit tests with 200 stations × 10 days run in seconds) but
explodes by ~3 orders of magnitude on real data.
**Fix applied:** Refactored to vectorised numpy. Per day, extract each
threshold's column once via ``t.column(col).to_pylist()`` → ``np.array``,
then compute a single boolean comparison against the threshold. OR-fold
across thresholds to get one per-station NG mask per day. Per-station
"first excursion reason" is computed lazily AFTER the hot loop —
only for the small set of already-flagged stations — so the formatting
overhead stays bounded.
**Result:** 32 s wall on the real 89-day × 1298-station × 121-threshold
workload. Same numerical output; unit tests still pass (12/12).
**Rule:** Any analysis that crosses ``n_rows × n_cols`` per-cell access
patterns must extract columns to numpy ONCE and operate vectorised.
``pa.Table.column(c).to_numpy(zero_copy_only=False)`` is the canonical
escape hatch; we use ``to_pylist() → np.asarray`` because some columns
are float64 with NaNs that numpy handles natively. Reserve per-row
pyarrow access for genuinely sparse work (e.g. resolving a debug
string for a station that's already flagged).
**Tags:** #perf #pyarrow #numpy #vectorisation #qualification

---

## [2026-05-16] testing: population-derived thresholds need spike count < 0.27% of pool

**Mistake:** First end-to-end test of ``analysis/qualification`` injected
spike values into 4 special stations across a 10-day window. The test
expected the spike values to *exceed* the derived 99.73th-percentile
threshold, but they consistently fell AT it, so the strict ``>`` check
never fired and the test failed. Time wasted: ~20 min of debugging.
**Root cause:** When the "bad" stations' spike samples occupy too large
a fraction of the metric pool, the 99.73th-percentile threshold gets
pulled INTO the spike-value cluster. Concretely: pool size ~1040, spike
count 31 → ~3% of pool, vastly more than the 0.27% tail the threshold
is meant to isolate. The sorted index ``int(n × 0.9973)`` lands inside
the spike cluster, so threshold = spike-value, and ``spike > threshold``
is False.
**Fix applied:** Designed the end-to-end test with three constraints
that keep each metric's spike fraction < 0.27%:
1. Each bad station spikes a DIFFERENT metric (so per-metric spike
   count stays small).
2. Bad stations spike on at most 3 days each (limiting per-metric
   spike count to ~3).
3. Baseline cohort is large enough (200 stations × 10 days = 2000
   samples) that 3 spikes is ~0.15% of pool — comfortably below
   the 0.27% threshold-pull boundary.
**Rule:** When unit-testing population-derived percentile thresholds,
the test injector must respect the threshold's own boundary. Quick
sanity check: ``spike_count / pool_size < (1 - percentile)``, e.g.
< 0.0027 for the 99.73th percentile. Violating this means the
threshold gets dragged INTO the spike cluster and downstream
comparisons silently flip semantics. Document the math inline in the
test docstring so future maintainers don't repeat the mistake.
**Tags:** #testing #qualification #percentile #unit-tests

---

## [2026-05-14] ops: disk-full mid-batch halted DOY 116 + harness lock-up at 0 bytes free

**Mistake / context:** During the April re-run, the workstation's
``/System/Volumes/Data`` filled to 100% (119 MiB free out of 228 GiB)
mid-way through DOY 116 (April 26). ``rnx2rtkp`` workers cascaded
``OSError: [Errno 28] No space left on device`` errors for ~20 stations
within seconds. Worse, ``/private/tmp`` was on the same volume, so
Claude Code's per-Bash output capture started failing with ``ENOSPC``,
preventing even basic ``df`` / ``rm`` commands from running through the
harness. Manual user intervention via terminal was needed to free space.
**Root cause (two compounding issues):**
1. **No pre-flight disk check.** ``april_process.sh`` happily kicked off
   day N's acquisition + processing without verifying free space first.
   Each day's working set peaks around 14 GB (7 GB RINEX + ~4 GB
   gunzipped workspace + ~2.6 GB .pos × 2 modes). Crossing the threshold
   silently was the structural failure.
2. **Skipped-day partials never cleaned.** When ``acquire-rinex`` timed
   out on DOY 107 and 109 (transient GSI FTP failures), the script
   ``continue``d to the next day WITHOUT removing the partially-downloaded
   RINEX (640 MB and 5.2 GB respectively). These accumulated alongside
   the day-output growth.
**Fix applied:**
- ``scripts/april_process.sh`` now runs a pre-flight ``df -g`` check at
  the top of every per-day loop iteration; aborts the batch (``exit 1``)
  if free space < ``MIN_FREE_GB`` (default 15 GB, overrideable). This is
  loud-fail: the partial run stops cleanly instead of cascading errors.
- Recovery procedure: drop partial DOY RINEX dirs (``data/raw/rinex/2026/
  {107,109,116}``), partial outputs from the failed DOY, and any stale
  benchmark trees (``data/processed/kinematic_p30_verify_nolapack/``).
- Resumed via 3 chained job invocations covering 7 missing DOYs
  (107, 109, 116-120). All 7 completed cleanly. Final state: 30/30
  days × 2 modes = 60 successful runs, 0 failed stations across 77,925
  per-station provenance rows.
**Rule:**
- Pre-flight resource checks (disk, memory) belong at the top of every
  long-running batch loop iteration. The cost of one ``df`` call per
  day is negligible; the cost of a half-failed mid-day cascade is hours
  of operator time + partial state to disentangle.
- When a step fails and the loop ``continue``s to the next iteration,
  the failed step's partial artefacts must be cleaned up explicitly in
  the same SKIP path — don't leave them for "the next sweep" because
  the next sweep may never come.
- macOS ``/private/tmp`` shares the system volume; a batch that writes
  several GB to ``data/`` can starve the harness's own output capture.
  Keep working-set forecasts honest and leave at least one safety
  margin's worth of headroom (10-15 GB).
**Tags:** #ops #disk-full #preflight #cleanup #batch #partial-state

---

## [2026-05-12] aux-data: shipped igs14_L5copy.atx / igu00p01.erp untraceable, stale

**Mistake / context:** First full-month CLASLIB processing run for April
2026 was launched against ``vendor/pntmoni-claslib/data/igs14_L5copy.atx``
and ``vendor/pntmoni-claslib/data/igu00p01.erp`` — files shipped with the
CLASLIB fork. User flagged that (a) igs20.atx and igu00p01.erp are
mutable upstream and need provenance, (b) the shipped L5copy ATX has
no audit trail to the igs20.atx revision it derives from, (c) per-station
rectype/anttype substitutions were only traceable via per-station .conf
files on disk, not in a structured log.
**Root cause:** Phase 0 verify path was a fast shortcut. The
``configs/kinematic_p30_verify.conf`` lessons-entry (2026-05-09) noted
that newer igs20.atx + clas_grid_003.def were "not yet staged"; we kept
running on the shipped versions instead of building the production
acquisition path early. The shipped ``igu00p01.erp`` ended at MJD
59992.25 (2023-02-17) — **1180 days stale** vs the 2026-04 target.
**Fix applied:**
- ``acquisition/igs_atx.py``: fetches ``https://files.igs.org/pub/station/general/igs20.atx``
- ``acquisition/igs_erp.py``: fetches ``https://cddis.nasa.gov/archive/gnss/products/igu00p01.erp.Z``
  via the existing Earthdata cross-origin redirect helper; ``.Z``
  (LZW) decompression via ``/usr/bin/uncompress`` (macOS ``gunzip``
  does NOT support .Z)
- ``processing/_aux_data.build_l5copy``: deterministic patcher — for
  every antenna block with F02 present but F05 missing, inserts an F05
  frequency sub-block copying the F02 PCV. Scope: GPS (G02→G05),
  QZSS (J02→J05). ``# OF FREQUENCIES`` is bumped to match. Output
  header carries PNTMONI COMMENT lines documenting source SHA-256,
  algorithm version, and insert counts.
- ``processing/_station_provenance``: per-(station, date, mode) JSONL
  record at ``data/metadata/station_config.jsonl`` capturing receiver,
  antenna, config_hash, and SHA-256 of every aux file the mode config
  referenced (file-rcvantfile, file-eopfile, file-blqfile, …).
- ``cli/acquire.py``: ``acquire {igs-atx, igs-erp, aux-data}``; the
  umbrella ``acquire aux-data`` fetches both + builds the L5copy
  derivation + stages everything into ``configs/aux_data/``.
- Verify configs (``kinematic_p30_verify.conf``,
  ``kinematic_p30_ttff_verify.conf``) now reference
  ``data/igs20_L5copy.atx`` and resolve via ``--data-dir configs/aux_data``.
**Live numbers (fetched 2026-05-12):**
- ``igs20.atx``: 56.5 MB, 905 antennas (vs shipped 793 — newer release)
- ``igs20_L5copy.atx``: 59.7 MB, **G05 inserts=432, J05 inserts=8**
- ``igu00p01.erp``: 3.28 MB, fresh today
- Single-station smoke test (0001 / 2026-04-03 / verify mode):
  97.6% Q=4 (RTK FIX), 2.4% Q=5, 1 Q=1 (initial convergence)
**Rule:** Aux files referenced by a processing config MUST be:
(a) acquired with URL + SHA-256 + retrieved_at recorded, (b) derived
files reproducibly built from a source whose SHA-256 is also recorded,
(c) every per-station processing run logs the SHA-256 of every aux
file used. Anything checked into ``vendor/...`` is a frozen snapshot
that needs explicit refresh — never trust an upstream-mutable file to
stay current just because it sits on disk.
**Tags:** #aux-data #igs20 #l5copy #provenance #atx #erp #reproducibility

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

---

## [2026-05-17] design + empirical: registry qualification-merge + eval_only / qualified monthly numbers

**Context**: First 30-day R5.1 monthly (the entry directly below)
landed `eval_only` and `qualified` station_set rows as NaN because
`_registry.load()` derives `is_eval` strictly from
`eval_periods.toml`, and the toml's latest entry ends 2025-09-30
(fy2025_1st_h). Target dates in 2026-04 fell into the gap and
nothing matched. The Monthly **速報** product (R5.1, per ADR 0013)
is not supposed to wait on the next QSS Service Performance Report
publication (`fy2026_1st_h`, expected ~2026-10) — the operative
eval set should fall through to the latest published period.

**Design**: Added a `qualification_path: Path | None` parameter to
`analysis._registry.load()` and a `--qualification` CLI flag to
`analyze {accuracy,ttff-stats,monthly}`. When supplied, the
station_qualification parquet (produced by `analyze qualification`,
which already has the latest-period fallback for `force_eval`)
overrides per-station `is_eval`, `qc_pass`, `qualified`, and adds
`out_of_service`. The merge:
- `is_eval` ← `force_eval` (CLAS 72 with latest-period fallback)
- `qc_pass` ← parquet's `qc_pass` (rolling-window QC, 90 d)
- `qualified` ← parquet's `qualified` (`(qc_pass | force_eval) & ~oos`)

The CLI flag is **opt-in**, deliberately: the Monthly **続報** (F5.1)
path may want strict period matching once `fy2026_1st_h` enters
`eval_periods.toml`. The flag preserves both semantics behind one
codepath.

**Empirical — 2026-04 numbers with the merge applied**
(qualification = `data/processed/station_qualification/2026-04-30_90d.parquet`:
  1300 rows, qualified=1033, qc_pass=1014, force_eval=72, oos=2):

verify (no-reset) — national, all/all/all:
| station_set | n | fix_rate | hor_p50 | hor_p95 | hor_p99 | ver_p95 |
|---|---|---|---|---|---|---|
| all         | 1298 | 97.34 % | 21.9 mm | 110.8 mm | 198.6 mm | 183.2 mm |
| eval_only   |   72 | 97.50 % | 22.3 mm | 113.8 mm | 196.2 mm | 189.3 mm |
| qualified   | 1033 | 97.67 % | 21.8 mm | 104.8 mm | 177.0 mm | 173.4 mm |

ttff_verify (15-min resets) — national, all/all/all:
| station_set | n | fix_rate | hor_p50 | hor_p95 | hor_p99 | ver_p95 |
|---|---|---|---|---|---|---|
| all         | 1298 | 75.44 % | 26.5 mm | 245.2 mm | 912.4 mm | 456.0 mm |
| eval_only   |   72 | 75.76 % | 26.9 mm | 230.5 mm | 868.2 mm | 434.4 mm |
| qualified   | 1033 | 75.80 % | 26.3 mm | 225.9 mm | 874.3 mm | 422.6 mm |

TTFF (ttff_verify, network=all/all/all):
- all (1294): fix_success_rate 97.82 %, ttff_p99 = 510 s
- eval_only (72): 97.70 %, ttff_p99 = 450 s — cleanest, by design (QSS-curated)
- qualified (1031): 98.19 %, ttff_p99 = 480 s

**Three findings worth carrying forward**:

1. **`qualified` outperforms `all` modestly** (+0.33 pp fix_rate verify;
   −6 mm hor_p95; −10 mm ver_p95). The signal exists but is small at
   the *national* aggregate level — the qualification step is doing
   the right thing (removing genuine problem stations) without
   distorting the aggregate. Per-network drill-down will show
   bigger gaps where southern-island difficulty concentrates.

2. **`eval_only` ≈ `qualified` to ~0.1 pp**: the CLAS 72 official
   set is already covered by the QC-pass criterion, so the
   `force_eval` overlay is mostly redundant at the monthly aggregate.
   It still matters at the per-network level (southern islands —
   the 15 force-eval rescues per lessons 2026-05-16) — *don't drop
   `eval_only` as a category* even though headline numbers coincide.

3. **`qualified` is the right default for the Free Monthly 速報**:
   it answers "how well does CLAS perform on stations that are
   actually fit-for-evaluation?", which is the question subscribers
   will read into the headline number. `all` is the more permissive
   reference; `eval_only` is the QSS-aligned reproducibility set.
   Publish all three; lead with `qualified`.

**Rule**: When upstream metadata (eval_periods.toml) lags behind the
target date, the right reflex is **not** to backfill the metadata
with a guess — it is to add an explicit override mechanism so the
operator's decision (which fallback to use) is visible in the run's
provenance (`--qualification <path>`). The 速報 / 続報 distinction is
the use-case template: same dataset, two acceptable readings, both
auditable.
**Tags:** #registry #qualification #r5 #monthly #2026-04 #adr-0013 #design

---

## [2026-05-17] empirical: first 30-day R5.1 monthly aggregate (2026-04, kinematic_p30_ttff_verify)

**Context**: First full-month rollup of the post-ADR-0013 pipeline,
using the R5.1 (Rapid) reference for the entire 2026-04 月 (DOY 091–120,
30/30 days OK, 32 min wall in-process). Mode is
`kinematic_p30_ttff_verify` (TTFF resets every 900 s); n = 1298
stations, 111.99 M epochs pooled. This is the **baseline** the
Monthly 速報 report will quote on going forward.
**Numbers (station_set=all)**:
- **fix_rate**: 75.44 % all / 76.06 % day / 74.71 % night
- **hor_p50 / p95 / p99**: 26.5 / 245.2 / 912.4 mm
- **ver_p50 / p95 / p99**: 40.2 / 456.0 / —
- inside (CLAS coverage) vs outside: 75.81 % / 74.72 % fix_rate;
  hor_p95 235.8 / 264.9 mm — outside marginally noisier as expected
- TTFF (network 1, n_stations=8): fix_success_rate 95.7 % all /
  99.5 % day / 91.2 % night, ttff_p50 = 180 s, ttff_p95 = 300 s
**Methodological note — TTFF resets cost ~22 pp fix_rate** (measured):
the parallel `kinematic_p30_verify` (no-reset) monthly for the same
period and station set landed at **fix_rate = 97.34 % all**,
hor_p95 = 110.8 mm, hor_p99 = 198.6 mm, ver_p95 = 183.2 mm. The TTFF
mode's `misc-regularly = 900` reset zeroes the filter every 15 minutes,
and the first ~3 minutes of each reconvergence land in Q=5/Q=1.
Concretely:
- fix_rate: verify **97.34 %** vs ttff_verify **75.44 %** → **−21.90 pp**
- hor_p95: 110.8 mm → 245.2 mm (**× 2.2** inflation)
- hor_p99: 198.6 mm → 912.4 mm (**× 4.6** inflation, dominated by
  in-convergence epochs)
- ver_p95: 183.2 mm → 456.0 mm (× 2.5)

This is structural to TTFF measurement; reports should always cite
which mode produced a quoted fix_rate, and the Monthly report
should publish **both** numbers — verify answers "what is CLAS
performance in steady-state?", ttff_verify answers "what is CLAS
performance including convergence?". They are not interchangeable
even on identical input.

**Methodological note — inside/outside delta is the Pro-tier signal**:
- verify mode, inside (CLAS coverage):   fix_rate 97.71 %, hor_p95 103.6 mm
- verify mode, outside:                  fix_rate 96.63 %, hor_p95 124.9 mm
- verify mode, outside_wo_southern:      fix_rate 96.75 %, hor_p95 119.7 mm

The "outside minus southern islands" 1 pp gap captures the
ionospheric / coverage-edge cost of Okinawa + Ogasawara stations
specifically. This is exactly the signal the Pro-tier per-station
drill-down is designed to surface (per ADR 0013 §2).
**Methodological note — day/night delta is small but consistent**:
~1.4 pp fix_rate drop and ~8 % ver_p95 inflation at night. This is
the ionospheric scintillation signature and is the empirical baseline
against which future seasonal / Solar-Cycle-25 trend detection will
be calibrated. The night window in this codebase is UTC 10–20
(≈ Japan local 19–05), so it captures the geomagnetic-quiet hours
correctly for the GEONET footprint.
**Rule**: When publishing the first national monthly number from a
new methodology baseline, record it in lessons as a *frozen
reference point*. Future regressions in fix_rate or accuracy
percentiles are easiest to detect against a labelled prior number
("the 2026-04 R5.1 baseline was 75.4 % all / hor_p95 245 mm")
rather than diff-from-noise. Also lock the mode label in the same
record — fix_rate values are not comparable across `verify` vs
`ttff_verify` even on identical input.
**Tags:** #monthly #r5 #2026-04 #ttff #fix-rate #baseline #empirical

---

## [2026-05-17] empirical: R5.1 vs F5.1 reference delta is sub-mm at GEONET aggregate scale (ADR 0013 §1 validated)

**Context**: First live computation of an R5.1-based reference_coords
parquet for **2026-04-01** (1301 stations, fixed_days_used=15/15)
side-by-side with the pre-existing F5.1-based parquet of the same date.
Both use the same ±7 d centred-median (CMR) algorithm and the same
Tsukuba1 (92110) anchor. The only difference is which GSI lineage
populates the daily fixed-station + station series — R5.1 (Rapid,
~1-week latency, IGR ephemerides) vs F5.1 (Final, ~1-month latency,
IGS ephemerides).
**Numerical delta (3D ECEF, across all 1301 stations)**:
- **p50 = 1.32 mm**
- **p95 = 1.66 mm**
- **max = 3.77 mm**
- Tsukuba1 anchor: (Δx, Δy, Δz) = (+0.60, +0.40, −1.10) mm
**Interpretation**: CLAS positioning errors are typically 10–30 cm
horizontal and a few decimetres vertical at GEONET stations. A 1–4 mm
reference-coordinate uncertainty between R5.1 and F5.1 is **two to
three orders of magnitude smaller** than the signal being measured, so
the choice of R5.1 vs F5.1 reference is methodologically immaterial
for national- and regional-aggregate CLAS evaluation. This is the
empirical baseline ADR 0013 §1 ("Reference precision adequacy at
aggregate level") asserted from theory; it is now backed by a live
measurement.
**Caveats**:
- p95 = 1.66 mm is the *typical* upper bound across a quiet day at a
  large station set. The same comparison **near recent deformation
  events** (volcanic / post-seismic regions on the day of measurement)
  will be larger — R5 lacks the long-arc batch refinement that F5
  uses to capture rapid coordinate evolution. ADR 0013 §2 already
  flags this as why **R5 + per-station drill-down is not offered**.
- Comparison is for 2026-04-01 only; periodic re-measurement at
  monthly cadence is the right operational posture so a regression
  in either lineage is visible.
- IGR (Ultra-Rapid IGS products) vs IGS (Final products) is the
  upstream difference; downstream the CMR algorithm is identical, so
  any residual delta is the IGR/IGS gap propagated through Bernese.
**Rule**: When a methodological-equivalence claim (ADR §) bottoms out
in an empirical question ("how close are the two products actually?"),
publish a real number from a live run AND the date you measured it.
Numbers carry the methodology forward even after the operator who
made the call rotates off.
**Tags:** #reference-coords #r5 #f5 #adr-0013 #empirical #methodology

---

## [2026-05-17] design: downstream cubes (epoch_errors/accuracy/ttff) are not variant-namespaced — provenance carries the lineage

**Context**: After namespacing `reference_coords` by variant (see the
2026-05-16 design lesson directly below), the question naturally
arises whether `epoch_errors/`, `accuracy/`, `ttff/` and the monthly
rollups should also be variant-namespaced.
**Decision**: They should **not** be. The path layout remains
`{root}/{mode}/{year}/YYYYMMDD.parquet` (single-instance) and the
provenance JSONL identifies the reference variant via the
`ref_coords_source` field (which now contains the variant subdir,
e.g. `data/processed/reference_coords/r5_1/2026/20260401.parquet`).
**Rationale**:
- The 速報→続報 supersession is sequential: once F5.1 publishes,
  recomputing the cube from F5.1 (overwriting R5.1) is what we want.
  Both versions on disk would be a parallel-existence asymmetry the
  product model doesn't actually need.
- Downstream cubes are cheaply recomputable from the upstream
  reference_coords (~20–30 s per DOY × mode for epoch_errors; <5 s
  per Stage-2 stage). They are caches, not source-of-truth artefacts.
- Disk pressure: epoch_errors is ~75 MB / DOY / mode. Per April this
  is ~4.5 GB per mode-set; doubling for variant coexistence would
  add ~9 GB per month, which compounds quickly and amplifies the
  disk-full risk the 2026-05-14 ops lesson is already on record about.
- Provenance JSONL already names which reference variant was used
  (via the source path) so lineage auditability is preserved without
  duplicating cubes.
**Operational pattern**:
1. Compute reference_coords for R5.1 (`--f5-variant auto-rapid`)
2. Run epoch-errors → accuracy → ttff-stats → monthly with
   `--ref-variant r5_1` (or omitted; default auto-prefers Final but
   falls through to Rapid if Final missing)
3. Publish the Free Monthly **速報** from the resulting cubes
4. When F5.1 publication catches up to the ±7 d window, re-acquire
   F5.1, recompute reference_coords (`--f5-variant f5_1`), and re-run
   epoch-errors with `--ref-variant f5_1`. Cubes are overwritten;
   the Free Monthly **続報** is published from the refreshed cubes
**Rule**: When deciding what layers of a computation chain to
parameterise vs. overwrite, ask whether the parameter genuinely
distinguishes a *published artefact* (preserve, namespace) from
an *intermediate cache* (overwrite, rely on provenance for lineage).
Reference_coords is the published artefact behind 速報/続報 — it
must coexist. Downstream cubes are caches — they can be regenerated.
**Tags:** #design #reference-coords #epoch-errors #variant #adr-0013 #provenance

---

## [2026-05-16] design: reference_coords output must be variant-namespaced (R5 速報 ⇄ F5 続報)

**Context**: Per ADR 0013 (`pntmoni-docs/70-decisions/adr-0013.md`),
the Free Monthly **速報** runs against GSI's Rapid lineage (R5.1,
ITRF2020, ~1-week latency) and the Free Monthly **続報** runs against
the Final lineage (F5.1, ITRF2020, ~1-month latency) for the **same
calendar month**. Pre-ADR the pipeline assumed a single reference per
date and wrote `data/processed/reference_coords/{year}/YYYYMMDD.parquet`
— a layout that would silently overwrite a 速報 parquet when 続報 lands
(or vice versa).
**Fix applied**:
- `analysis/_reference_coords.output_path_for_day/_week` and the
  `analyze reference-coords` CLI now **always** namespace by variant
  (`{root}/{variant}/{year}/...`). The four variants `f5`, `f5_1`,
  `r5`, `r5_1` get disjoint subtrees.
- `ComputeResult.variant` and the parquet's per-row `variant` column
  carry the lineage downstream; provenance JSONL gains `variant` and
  `is_rapid` fields.
- `analysis/_epoch_errors.find_reference_coords_parquet` resolves
  variant-first. Auto-mode prefers Final (F5.1 > F5 > R5.1 > R5) so
  Stage-1 ENU recomputes naturally pick up 続報 when it lands; an
  explicit `--ref-variant r5_1` selects 速報.
- One-shot migration of 3 existing parquets (20260315, W11 → `f5/`;
  20260401 → `f5_1/`) — frame field in each row disambiguated which
  variant produced them.
**Rule**: When the product model intentionally republishes the same
target with a different upstream (速報 → 続報, draft → final, ITRF2014
→ ITRF2020), the on-disk layout must reserve disjoint paths from the
start. Single-target paths with implicit "the latest writer wins"
semantics are a future debugging trap. Encode the variant in the path,
the row, and the provenance simultaneously so any one can be lost
without losing the lineage.
**Tags:** #reference-coords #adr-0013 #r5 #f5 #variant #design

---

## [2026-05-16] methodology: ceil vs round when porting an integer ratio across granularities

**Mistake:** `ng_days_max = ceil(n_days × 0.038)` was inherited
verbatim from the legacy `station_stats` weekly-sample
implementation when the qualification module was ported to daily
granularity. Under weekly sampling `ceil(52 × 0.038) = ceil(1.976)
= 2` matches the original "2 NG per 52 weeks" intent — but at
daily granularity `ceil(89 × 0.038) = ceil(3.382) = 4` admits an
extra NG-day not present in the original methodology, producing an
effective ~4.5% tolerance against an intended 3.8%.
**Root cause:** `0.038` is itself an integer-ratio approximation
(`2/52`), so it represents a *centred rate*, not an *upper bound
on tolerance*. `ceil` treats it as the latter; `round` preserves
the former. The two functions are indistinguishable at the
original sample count, so the discrepancy was invisible until the
granularity changed.
**Fix applied:** Switched to `round`, bumped
`METHODOLOGY_VERSION` to `qual-v2`, regenerated the 2026-04-30
qualification parquet (50 stations flipped qualified →
not-qualified, none in geographic blind spots — force_eval
overlay rescued the 4 boundary force-eval stations), and recorded
the rationale + empirical impact in ADR 0011 Postscript.
**Rule:** When inheriting a rule expressed as an *integer
threshold* (e.g. "at most 2 of 52") and re-expressing it as a
*ratio applied to a different sample count*, audit whether the
rule's intent is a centred rate (use `round`) or an upper bound
(use `ceil` / `floor`). Document the choice in code and bump the
methodology version when correcting one.
**Tags:** #qc #qualification #methodology #legacy-porting

## [2026-05-20] claslib: CSSR dump capability is SSR2OSR/SSR2OBS -dump, not DUMPCSSR

**Mistake:** While auditing methodology §6 (L6 broadcast alert
detection) against the implementation, I concluded the CSSR
alert-flag dump mechanism was unavailable in pntmoni-claslib
v0.8.3 because the README states DUMPCSSR was "no longer supported
from version 0.4.0". I recommended deferring §6 to Phase 1 on that
false premise.
**Root cause:** I read only the DUMPCSSR removal note and did not
check that its functionality was folded into the SSR2OSR (and later
SSR2OBS) utilities, which expose a `-dump` option (README §3.1/§3.2).
The dump path in `src/cssr.c` even writes a CSV whose header
includes an `Alert Flag` column (cssr.c:4352), and frame-level
alerts are flagged at cssr.c:4120-4122 — exactly what §6 needs.
**Fix applied:** Corrected §6's mechanism wording to name
SSR2OSR/SSR2OBS `-dump` (Alert Flag CSV) rather than the removed
DUMPCSSR / a vague "dump 機能". Kept §6 as a v1.0.0-feasible
feature rather than deferring it.
**Rule:** Before declaring a vendored tool's capability "removed"
or "missing", grep the source for the underlying function — a
removed CLI front-end (DUMPCSSR) does not mean the capability is
gone; it is often merged into a successor utility (SSR2OSR -dump).
**Tags:** #claslib #cssr #l6 #methodology #verification

## [2026-06-02] qmd: matplotlib.hexbin ignores cartopy `transform=`, bins in axes-native coords

**Mistake:** First implementation of the §空間分布 figure used
``ax.hexbin(lon, lat, C=value, ..., transform=ccrs.PlateCarree())``
inside a cartopy Albers axes. The hex layer rendered empty — no error,
no warning, just a blank map under the coastline chrome.
**Root cause:** ``matplotlib.hexbin`` is a Collection generator that
bins points BEFORE rendering, and it bins in the axes' native
coordinate system. ``transform=`` is honoured for the FINAL Polygon
rendering but not for the binning step. With Albers axes (units =
metres) fed PlateCarree lon/lat (units = degrees), every bin centre
landed at ~130 m (literal value of the longitude) so all hexes
fell outside the ~3000 km Albers extent and were clipped.
**Fix applied:** Pre-project the data once in the hex-spatial-setup
cell using ``_PROJ_AEA.transform_points(ccrs.PlateCarree(), lon, lat)``
and feed the resulting Albers (x, y) columns to hexbin without a
``transform=`` kwarg. ``gridsize=50`` over the ~3000 km projected
width yields ~60 km flat-to-flat hexes, matching the CLAS spec
grid spacing.
**Result:** Hexes render at correct ground positions in Albers
projection, sized consistently across the Japan archipelago (no more
latitude-dependent visual distortion from the previous manual-polygon
PlateCarree approach).
**Rule:** Any matplotlib binner (``hexbin``, ``hist2d``) used inside
a non-rectangular cartopy axes must receive data ALREADY projected to
the axes' coordinate system. ``transform=`` only fixes the rendering
half of the pipeline. ``scatter``, ``plot``, ``add_patch`` honour
``transform=`` end-to-end and do not need pre-projection.
**Tags:** #matplotlib #cartopy #hexbin #quarto #figures

## [2026-06-02] pandas: groupby('col').apply(g.sample(...)) silently drops the grouping column

**Mistake:** The hex-data load cell stratify-sampled epoch errors via
``df.groupby("station", group_keys=False).apply(lambda g: g.sample(n=80))``
and then merged the result with station coordinates on ``"station"``.
The merge raised ``KeyError: 'station'``. Because the qmd cell wrapped
the whole try block in ``except Exception``, ``HEX_REAL_DATA`` stayed
``False`` and the rapid render quietly fell through to the synthetic
preview path — the 速報 banner and stream tag updated but the hex map
showed synthetic data instead of real April values.
**Root cause:** In pandas 2.2+ ``groupby.apply`` strips the grouping
column from the returned DataFrame even when ``group_keys=False``
(the latter only controls the index, not whether the column is
preserved as a column). The ``include_groups=False`` flag is the
explicit knob, but the default behaviour changed without a
deprecation warning visible in our usage.
**Fix applied:** Replaced the pattern with shuffle-then-head:
``df.sample(frac=1, random_state=42).groupby("station", group_keys=False).head(80)``.
Equivalent semantics (stratified per-station random subset, capped at
80) but operates on rows already containing the station column.
**Rule:** Never rely on ``groupby('X').apply(...)`` retaining the
``X`` column in pandas 2.x. Either use ``include_groups=False`` AND
``reset_index()``, or rewrite as ``sample(frac=1).groupby('X').head(n)``
/ ``df.assign(_rnd=…).groupby('X').nsmallest(n, '_rnd')`` — both
preserve the column trivially. Bonus rule: never wrap a multi-step
pipeline in a bare ``except Exception`` without logging the exception
type — it hides exactly this kind of silent fallback.
**Tags:** #pandas #qmd #report #debugging

## [2026-06-02] driver: TTFF parquets must be read from the paired `_ttff_verify` mode, not the accuracy mode

**Mistake:** The monthly report's TTFF headline table showed
P50 = 0 s, P95 = 0 s, P99 = 300 s, success = 98.25 % for April 2026.
The numbers were technically loaded from a real parquet, but they
were meaningless: every reset window's TTFF was 0 because there were
no resets to start the timer from.
**Root cause:** The driver hardcoded
``ttff_*_monthly/<mode>/<period>.parquet`` using the same ``mode``
as accuracy (``kinematic_p30_verify``). That mode runs CLAS
continuously — there is no periodic reset — so its "TTFF" is
just "time of first epoch", which is always at t=0 of the
processing run. Per methodology §5.2, TTFF requires periodic 15-min
resets and is processed in a paired ``_ttff_verify`` mode
(``kinematic_p30_ttff_verify``) which already existed and produced
the real numbers (P50=180, P95=300, P99=480, success=98.19%) — the
driver just never looked there.
**Fix applied:** New ``_ttff_mode_for(mode)`` helper maps the
accuracy mode to its TTFF twin (``_verify`` → ``_ttff_verify``,
preserved if already ``_ttff``). Driver exposes a ``ttff_mode=``
kwarg defaulting to that derivation; the TTFF parquets are routed
through it.
**Rule:** TTFF and accuracy are NOT just different aggregations of
the same processing run — they require different processing modes
(reset vs continuous) and therefore different mode-namespaced parquet
trees. Any code that loads "the TTFF parquet for this period" must
derive the TTFF-specific mode from the caller's accuracy mode, never
reuse it directly. Same rule will apply to future mode pairs (Phase 1+
60-min reset → ``_ttff60_verify``).
**Tags:** #ttff #methodology #driver #report

## [2026-06-02] constellation: NAVCEN GPS lists ALL active NANUs including future-scheduled FCSTSUMM

**Mistake:** First version of the GPS constellation scraper mapped
``NANU Type == "FCSTSUMM"`` (forecast summary) to status ``outage``.
The resulting report flagged 27 of 31 GPS satellites as currently
down — clearly wrong, since the constellation is functionally healthy.
**Root cause:** The NAVCEN GPS page lists every satellite that has at
least one *active* NANU on its books. "Active" includes scheduled
maintenance windows months in the future (FCSTSUMM) and historical
extensions still on file. At any given time most GPS satellites have
a pending FCSTSUMM, so "active NANU" is the norm, not an exception.
**Fix applied:** Status mapping restricted to currently-in-effect
notices: ``DECOMMISSION`` → ``decommissioned``, ``UNUSUFN``
(Unusable Until Further Notice) / ``UNUSANO`` / subject contains
``UNUSABLE`` or ``UNAVAILABLE`` → ``unusable``. Everything else,
including FCSTSUMM and DELAYED, stays ``operational`` — the notice
details remain in ``notice_type`` / ``notice_subject`` columns so a
reader sees "scheduled maintenance on 04 SEP 2025" but doesn't
mistake it for "currently down".
**Rule:** When scraping operator-facing notice boards, distinguish
"has an active notice" from "is currently in the state the notice
describes". Effective-date / start-date / end-date logic must be
applied per-notice; relying on the notice's mere presence to infer
current status almost always overcounts. For GPS NANUs specifically,
the in-effect types are ``UNUSUFN`` / ``UNUSANO`` / ``DECOMM`` —
treat all others as informational unless paired with date-range
evaluation.
**Tags:** #constellation #gps #nanu #scraping

## [2026-06-02] edit-safety: bulk regex `re.sub(r"  +", " ", src)` destroys YAML / Python indentation

**Mistake:** While cleaning ADR / IASB references from
``monthly_free.qmd`` I batched the edits with a Python script using
``re.sub(r"\(\[ADR [0-9]+[^]]*?\]\([^)]*\)\)", "", src)`` etc.,
and finished with a cosmetic ``re.sub(r"  +", " ", src)`` to collapse
the trailing whitespace artefacts. The latter collapsed every multi-
space run including all YAML and Python indentation in code cells.
The 590-line diff (308 ins / 282 del) made the qmd unrenderable;
``git checkout`` was needed to recover.
**Root cause:** ``re.sub(r"  +", " ", src)`` matches "two or more
spaces" anywhere — including the leading whitespace of indented YAML
keys (``  toc: true``) and Python bodies (``    with open(_pp) as
_fp:``). In a file format that mixes prose with indented code blocks,
no whitespace-collapse heuristic is safe at file scope.
**Fix applied:** Reverted via ``git checkout``, re-applied the ADR
removals as discrete ``Edit`` tool calls with full surrounding
context. Each call is bounded and visible in the diff. Adding three
sentinel checks (``ADR``, ``IASB``, ``Free Live Dashboard`` count =
0 after edits) confirmed completeness without resorting to a sweep.
**Rule:** Never run a file-scope whitespace-collapsing regex on a
file format that carries semantic whitespace (YAML, Python, Quarto
.qmd, Markdown indented code blocks, Makefile). Bulk edits in such
files must be either (a) per-edit through the ``Edit`` tool — slow
but safe — or (b) regex restricted to runs of three or more spaces
INSIDE non-indented prose, with explicit anchors (``(?<=\S)  +(?=\S)``
to require non-space context). Diff size > 10× the count of intended
changes is the early-warning sign — STOP and inspect before any
git operation.
**Tags:** #edit-safety #quarto #yaml #python
