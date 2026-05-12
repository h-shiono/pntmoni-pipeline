# Reports

Quarto sources for PNT Moni's evaluation reports. Outputs are
gitignored; run a render to produce them locally.

## Templates

- [`templates/monthly_qc.qmd`](templates/monthly_qc.qmd) — free-tier
  monthly QC report (GEONET observation quality only; no positioning)
- `templates/monthly.qmd` — full canonical monthly (synthetic data
  scaffolding; positioning + QC, Phase 0 launch target)

## Rendering

### Prerequisites

- Quarto CLI (`quarto --version` ≥ 1.9)
- Python toolchain for the data binding (Jupyter, pandas, matplotlib,
  pyarrow, cartopy, tabulate). When invoking via `uv run`, pass them
  as `--with` flags (see commands below) or add them to a
  project-level dependency file.
- For **PDF** rendering only:
  - MacTeX (or any TeX Live with `xelatex`)
  - macOS system Japanese fonts (Hiragino — preinstalled on macOS)

The PDF format block in `monthly_qc.qmd` is configured for macOS:
`Helvetica Neue` for Latin, `Hiragino Sans` for CJK. To swap in the
PNT Moni brand fonts (Inter, Noto Sans JP) install them locally and
edit the `mainfont` / `CJKmainfont` keys in the qmd frontmatter.

### Render both HTML and PDF

```bash
uv run \
    --with jupyter --with pyyaml --with pandas --with matplotlib \
    --with pyarrow --with cartopy --with tabulate \
    quarto render reports/templates/monthly_qc.qmd
```

### Render only one format

```bash
# HTML only (fast, no LaTeX needed)
quarto render reports/templates/monthly_qc.qmd --to html

# PDF only
quarto render reports/templates/monthly_qc.qmd --to pdf
```

Outputs land in [`output/templates/`](output/) (gitignored).

## Inputs

`monthly_qc.qmd` binds to per-DOY parquets under
`data/processed/qc_summary/<year>/<YYYYMMDD>.parquet`. Produced by:

```bash
pntmoni-pipeline qc teqc      --date YYYY-MM-DD
pntmoni-pipeline qc summarize --date YYYY-MM-DD
```

The setup chunk loads every parquet matching `<year><month>*.parquet`
for the report's `year` / `month` parameters.
