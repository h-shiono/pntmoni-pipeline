// pntmoni brand tokens v1.2.0 — GENERATED from pntmoni-docs/60-brand/tokens.json
// Do not hand-edit. Regenerate: node 60-brand/generate-tokens.mjs (see ADR 0017)

// brand palette (editorial only)
#let pm-ink       = rgb("#22273A")
#let pm-blue      = rgb("#1F5AA6")
#let pm-blue-deep = rgb("#16406E")
#let pm-gold      = rgb("#E8C438")
#let pm-cream     = rgb("#EFF0EB")
#let pm-text      = rgb("#3A4152")
#let pm-muted     = rgb("#6B7384")
#let pm-faint     = rgb("#8A93A6")
#let pm-on-dark   = rgb("#C7CCD8")
#let pm-border    = rgb("#E4E4E6")

// data palette (figures only — never brand gold)
#let pm-seq       = (rgb("#DCE6F1"), rgb("#A9C4E0"), rgb("#6E9BC8"), rgb("#2E6DA8"), rgb("#16406E"))
#let pm-normal    = rgb("#2E8B6B")
#let pm-degraded  = rgb("#E08A1E")
#let pm-critical  = rgb("#C24B3A")

// fonts (report headings = sans; numbers = mono with tabular figures)
#let pm-sans = ("IBM Plex Sans JP", "Noto Sans JP")
#let pm-mono = ("IBM Plex Mono",)
#let pm-num(body) = text(font: pm-mono, features: ("tnum",))[#body]
