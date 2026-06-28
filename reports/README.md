# Reports

Quarto sources for PNT Moni's evaluation reports. Outputs are
gitignored; run a render to produce them locally.

## Templates

All templates are **bilingual (JA/EN) from a single source** — see
[Bilingual rendering](#bilingual-rendering-ja--en).

- [`templates/monthly_qc.qmd`](templates/monthly_qc.qmd) — free-tier
  monthly QC report (GEONET observation quality only; no positioning).
  Rendered manually with `quarto render ... --profile {ja|en}`.
- [`templates/monthly_free.qmd`](templates/monthly_free.qmd) — free-tier
  monthly CLAS performance report (positioning accuracy, TTFF, spatial
  hex maps). Driven by the pipeline: `pntmoni-pipeline report monthly
  --render` renders both languages (`--langs ja,en` by default) into
  `<out>/<stream>/<period>/<lang>/`.
- [`templates/monthly_pro.qmd`](templates/monthly_pro.qmd) — Pro-tier
  report (not yet bilingual).

## Bilingual rendering (JA / EN)

Templates are **bilingual from a single source**. Language is selected
by a Quarto profile; one switch drives everything:

```bash
# Japanese
quarto render reports/templates/monthly_qc.qmd --profile ja --no-execute-daemon
# English (also the no-profile default)
quarto render reports/templates/monthly_qc.qmd --profile en --no-execute-daemon
```

`--no-execute-daemon` is **required**: the template's Python reads the
active language from `QUARTO_PROFILE`, and the jupyter execute-daemon
caches the first render's kernel/env — a cached kernel would keep a
stale profile, so a JA render right after an EN one would silently come
out English.

How the switch fans out (see `reports/_quarto-{ja,en}.yml` and the
template's `setup` cell):

- **Prose / headings / callouts** — `::: {.content-visible
  when-profile="ja|en"}` blocks; both languages live side by side.
- **Figure / table captions** — `#| fig-cap: "{{< meta caps.qc.KEY >}}"`;
  the text lives in the profile YAML's `caps:` tree.
- **Title / subtitle** — `{{< meta title_qc >}}` from the profile.
- **Python-emitted text** (matplotlib titles/axis labels, table
  headers/rows, `output: asis` prose) — a `STR[LANG]` catalog + `T()`
  helper, keyed off `QUARTO_PROFILE`.

The compute/plot code exists **once** — only the strings switch.
Confirmed Japanese terminology lives in
`~/.claude/.../memory/report-ja-glossary.md`.

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
quarto render reports/templates/monthly_qc.qmd --to html --profile ja --no-execute-daemon

# PDF only
quarto render reports/templates/monthly_qc.qmd --to pdf --profile ja --no-execute-daemon
```

Add `--profile ja` / `--profile en` to pick the language (see
[Bilingual rendering](#bilingual-rendering-ja--en) above); omitting it
defaults to English. Always pass `--no-execute-daemon` for bilingual
renders. Outputs land in [`output/templates/`](output/) (gitignored).

## Inputs

`monthly_qc.qmd` binds to per-DOY parquets under
`data/processed/qc_summary/<year>/<YYYYMMDD>.parquet`. Produced by:

```bash
pntmoni-pipeline qc teqc      --date YYYY-MM-DD
pntmoni-pipeline qc summarize --date YYYY-MM-DD
```

The setup chunk loads every parquet matching `<year><month>*.parquet`
for the report's `year` / `month` parameters.
