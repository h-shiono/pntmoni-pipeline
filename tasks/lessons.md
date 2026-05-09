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
