"""Brand-discipline lint (ADR 0017 Phase E) as part of the test suite.

The standalone check lives in ``scripts/check_brand_discipline.py``;
this wrapper makes ``pytest`` the single entrypoint that also enforces
the dual-palette rule (brand gold #E8C438 never in figure code).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_brand_discipline.py"
_spec = importlib.util.spec_from_file_location("check_brand_discipline", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def test_no_brand_gold_in_template_python_cells():
    findings = _mod.check_gold_in_qmd_python_cells()
    assert not findings, (
        "brand gold #E8C438 must never appear in figure/code contexts "
        "(ADR 0017 dual-palette discipline):\n" + "\n".join(findings)
    )


def test_status_hexes_not_ui_decorative_in_scss():
    # Best-effort heuristic — warnings only, surfaced via pytest -ra
    # if they ever appear; not a hard failure by design.
    warnings = _mod.check_status_hex_in_scss()
    if warnings:
        import warnings as _w
        for w in warnings:
            _w.warn(f"brand discipline: {w}", stacklevel=1)
