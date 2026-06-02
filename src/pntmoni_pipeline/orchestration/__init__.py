"""Workflow orchestration for the per-DOY pipeline chain.

This package binds the already-idempotent per-DOY building blocks
(acquisition → CLASLIB positioning → teqc QC → QC summarize) into a
single ``daily`` driver and a resumable ``backfill`` driver over a date
range. It adds no new analysis or report capability — it only sequences
the existing engine entrypoints, isolates failures, and records a
structured status per run.

See ``tasks/todo.md`` (2026-06-02 task) for the design rationale.
"""
from __future__ import annotations

from ._steps import StepResult
from .backfill import BackfillResult, run_range
from .daily import DEFAULT_MODES, DayResult, run_day

__all__ = [
    "StepResult",
    "DayResult",
    "BackfillResult",
    "run_day",
    "run_range",
    "DEFAULT_MODES",
]
