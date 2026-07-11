-- reports/templates/pntmoni-date.lua — honor initial_pub_date in the
-- HTML title-block banner on correction re-renders.
--
-- Background: the monthly templates' frontmatter carries `date: today`
-- so a standalone render (template preview / synthetic mode, no
-- driver) always shows a sensible date. But on a CORRECTION re-render
-- of an already-published edition, "today" is the render date, not the
-- original v1.0 publication date — the PDF cover and revision table
-- already get this right via the INITIAL_PUB_DATE Python variable
-- (params cell, fed by PNTMONI_REPORT_PARAMS), but the HTML
-- title-block banner is driven by Quarto/pandoc's own `date` metadata
-- field, which code cells cannot rewrite after the fact.
--
-- Fix: the pipeline driver (src/pntmoni_pipeline/reports/driver.py,
-- render()) sets PNTMONI_TITLE_DATE to the resolved initial_pub_date
-- (ISO YYYY-MM-DD) whenever it is non-empty, and leaves it unset
-- otherwise. This filter overrides `date` from that env var when
-- present; unset/empty is a no-op, so `date: today` still governs
-- first publications and standalone/preview renders outside the
-- driver.
--
-- Quarto resolves `date: today` / applies date-format long BEFORE any
-- user Lua filter runs (verified empirically against Quarto 1.9.37 /
-- its bundled pandoc: a raw command-line `--metadata date:...` or
-- `--metadata-file` override is silently ignored whenever the
-- document's own YAML frontmatter already sets `date`, and a Meta()
-- filter assignment lands AFTER that formatting pass, so it must
-- supply an already-formatted string, not a plain ISO value). This
-- filter therefore reproduces the same long-form display Quarto's
-- default date-format already uses for the ja/en profiles (see
-- reports/_quarto-{ja,en}.yml `lang:`), so the override is visually
-- indistinguishable from a native frontmatter date — just pointing at
-- the correct (non-render-time) day. Scoped to the `date` field only;
-- everything else in meta passes through untouched.
local MONTHS_EN = {
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
}

function Meta(meta)
  local override = os.getenv("PNTMONI_TITLE_DATE")
  if not override or override == "" then
    return meta
  end
  local y, m, d = override:match("^(%d%d%d%d)-(%d%d)-(%d%d)$")
  if not y then
    -- Unrecognized format: show verbatim rather than fail the render.
    meta.date = pandoc.MetaString(override)
    return meta
  end
  y, m, d = tonumber(y), tonumber(m), tonumber(d)
  local lang = meta.lang and pandoc.utils.stringify(meta.lang) or "en"
  local formatted
  if lang:match("^ja") then
    formatted = string.format("%d年%d月%d日", y, m, d)
  else
    formatted = string.format("%s %d, %d", MONTHS_EN[m], d, y)
  end
  meta.date = pandoc.MetaString(formatted)
  return meta
end
