// reports/templates/typst-show.typ — Quarto typst-show partial override
// (ADR 0017 Phase D). Applies the `article` shell from
// typst-template.typ, passing the document title/subtitle (already
// resolved through the active language profile's metadata) — the
// provenance cover reuses them, so it follows the profile language.
#show: doc => article(
$if(title)$
  title: [$title$],
$endif$
$if(subtitle)$
  subtitle: [$subtitle$],
$endif$
$if(lang)$
  lang: "$lang$",
$endif$
$if(region)$
  region: "$region$",
$endif$
$if(section-numbering)$
  sectionnumbering: "$section-numbering$",
$endif$
$if(toc)$
  toc: $toc$,
$endif$
$if(toc-title)$
  toc_title: [$toc-title$],
$endif$
  toc_depth: $toc-depth$,
  doc,
)
