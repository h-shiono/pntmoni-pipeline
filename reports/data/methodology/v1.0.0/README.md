# scripts/figures/data

Small, **committed** reference / derived inputs shared across figure
generation scripts. Files here are **methodology-version-agnostic** —
methodology v1.0.0, v1.1.0, etc. may all consume the same grid
definition file. Files that are intrinsically version-bound belong in
`scripts/figures/v<X.Y.Z>/` instead.

## Inventory

| File | Source | Notes |
|---|---|---|
| `clas_grid.def` | QSS / Cabinet Office IS-QZSS-L6 spec (grid definition in use since IS-QZSS-L6-003, also valid for L6-004 and L6-008 as of 2026-05) | Upstream-verbatim plaintext. Columns: Compact Network ID, GRID No., latitude (deg), longitude (deg), ellipsoidal height (m). Source of the 12-network polygon derivation used in fig-01 / fig-02 |

Planned but not yet present (add as actual scripts land):

| File | Source | Notes |
|---|---|---|
| `network_polygons.geojson` | Derived from `clas_grid.def` + Shiono & Kubo 2025 polygon definition | Hand-derived; small (<100 KB) |
| `geonet_stations.csv` | terras.gsi.go.jp station list export | Trim to the columns used by figures |
| `out_of_service.toml` | PS-QZSS-003 (4 stations: 0604/0605/1098/1140) | Mirrors `qualification.jsonl` |

## Policy

**Do not commit raw upstream dumps.** If the input is large or
volatile, add a `fetch_<source>.py` in this directory that pulls it,
processes it down to a committed derived file, and document the source
URL + date in the script header.

`clas_grid.def` is an exception worth noting: it is committed verbatim
because it is the upstream canonical form, it is small, and its
provenance (IS-QZSS-L6 specification) is publicly documented and stable
across multiple specification revisions. If a future L6 specification
update changes the grid definition, **add a new file alongside this one
(e.g. `clas_grid_is-qzss-l6-XXX.def`) rather than overwriting** — past
methodology versions may need to reference the older definition for
reproducibility.
