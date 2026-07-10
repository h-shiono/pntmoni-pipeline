#!/usr/bin/env python3
"""Brand-discipline lint (ADR 0017 Phase E).

Dual-palette rules (source: pntmoni-docs/60-brand/tokens.json):

FAIL — brand gold ``#E8C438`` in figure/code contexts: any occurrence
    inside a ```{python} cell of ``reports/templates/*.qmd`` that sits
    inside a string literal (i.e. is real code, e.g.
    ``COLOR = "#E8C438"``). Occurrences outside string literals are
    necessarily Python comments — those state the prohibition and are
    allowed.

WARN — best-effort heuristic: a status hex (#2E8B6B / #E08A1E /
    #C24B3A) written literally in ``reports/styles/pntmoni.scss``
    outside a status-signalling context (.status-*, .kpi-delta-*,
    callout warning borders, badges). Status colors are data
    signalling, never UI decoration. The theme normally references
    them via the generated ``$pm-status-*`` variables, so any literal
    hex here deserves a look.

Usage: ``python scripts/check_brand_discipline.py`` (exit 1 on FAIL,
0 otherwise; warnings are printed but do not fail). Also wired into
pytest via ``tests/unit/test_brand_discipline.py``.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "reports" / "templates"
SCSS_FILE = REPO_ROOT / "reports" / "styles" / "pntmoni.scss"

GOLD = re.compile(r"e8c438", re.IGNORECASE)
STATUS = re.compile(r"#(2E8B6B|E08A1E|C24B3A)", re.IGNORECASE)
# SCSS contexts where a status hex is legitimate (figure/status
# signalling, not decoration).
SIGNALLING = re.compile(r"status|badge|delta|warning|caution|important|danger|signal", re.IGNORECASE)


def _in_string(line: str, pos: int) -> bool:
    """True if ``pos`` in ``line`` sits inside a ' or " string literal.

    Single-line heuristic (multiline strings are not tracked) — enough
    for the templates' setup cells, and errs on the side of flagging.
    """
    quote = None
    for i, ch in enumerate(line):
        if i >= pos:
            break
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
    return quote is not None


def check_gold_in_qmd_python_cells() -> list[str]:
    """FAIL findings: brand gold inside code (strings) in python cells."""
    findings = []
    for qmd in sorted(TEMPLATES.glob("*.qmd")):
        in_python = False
        for lineno, line in enumerate(qmd.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not in_python and stripped.startswith("```{python"):
                in_python = True
                continue
            if in_python and stripped == "```":
                in_python = False
                continue
            if not in_python:
                continue
            for m in GOLD.finditer(line):
                if _in_string(line, m.start()):
                    findings.append(
                        f"{qmd.relative_to(REPO_ROOT)}:{lineno}: brand gold "
                        f"#E8C438 in figure/code context: {stripped[:80]}"
                    )
    return findings


def check_status_hex_in_scss() -> list[str]:
    """WARN findings: literal status hexes outside signalling rules."""
    if not SCSS_FILE.is_file():
        return []
    warnings = []
    lines = SCSS_FILE.read_text(encoding="utf-8").splitlines()
    for idx, line in enumerate(lines):
        if not STATUS.search(line) or line.lstrip().startswith("//"):
            continue
        # Look at the line itself and up to 8 preceding lines (nearest
        # selector/comment context) for a signalling keyword.
        context = "\n".join(lines[max(0, idx - 8): idx + 1])
        if not SIGNALLING.search(context):
            warnings.append(
                f"{SCSS_FILE.relative_to(REPO_ROOT)}:{idx + 1}: status hex in "
                f"UI-decorative rule? {line.strip()[:80]}"
            )
    return warnings


def main() -> int:
    failures = check_gold_in_qmd_python_cells()
    warnings = check_status_hex_in_scss()
    for w in warnings:
        print(f"WARN  {w}")
    for f in failures:
        print(f"FAIL  {f}")
    if failures:
        print(f"\nbrand discipline: {len(failures)} failure(s) "
              f"(brand gold is editorial-only — ADR 0017)")
        return 1
    print(f"brand discipline: OK ({len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
