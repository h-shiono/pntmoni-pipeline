"""Step wrappers around existing engine entrypoints.

Each step runs one stage of the per-DOY chain, captures its own
exceptions, and returns a uniform :class:`StepResult` so the daily /
backfill drivers can sequence stages and report status without knowing
each engine's bespoke return shape. A step never raises: a failure is
reported as ``status == "failed"`` with the error text, so the driver
can isolate it and continue (continue-on-error).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

from ..acquisition import cddis_brdc, geonet_rinex, qzss_l6
from ..processing import claslib_engine
from ..qc import _summary, _teqc

logger = logging.getLogger(__name__)

#: One of ``ok`` | ``skipped`` | ``failed`` | ``partial``.
Status = str


@dataclass
class StepResult:
    """Uniform outcome of one orchestration step."""

    name: str
    status: Status
    n_total: int = 0
    n_ok: int = 0
    n_skipped: int = 0
    n_failed: int = 0
    wall_sec: float = 0.0
    error: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return self.status == "failed"

    def to_jsonable(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "n_total": self.n_total,
            "n_ok": self.n_ok,
            "n_skipped": self.n_skipped,
            "n_failed": self.n_failed,
            "wall_sec": round(self.wall_sec, 2),
        }
        if self.error:
            d["error"] = self.error
        if self.detail:
            d["detail"] = self.detail
        return d


def status_from_counts(n_total: int, n_ok: int, n_skipped: int, n_failed: int) -> Status:
    """Collapse per-station counts into a single step status."""
    if n_total == 0:
        return "failed"
    if n_failed == 0 and n_ok == 0 and n_skipped == n_total:
        return "skipped"
    if n_failed == 0:
        return "ok"
    if n_ok == 0 and n_skipped == 0:
        return "failed"
    return "partial"


def _guard(name: str, thunk: Callable[[], StepResult]) -> StepResult:
    """Run ``thunk``, timing it and converting any exception to a failed step."""
    t0 = time.monotonic()
    try:
        res = thunk()
        res.wall_sec = time.monotonic() - t0
        return res
    except Exception as exc:  # noqa: BLE001 — deliberate continue-on-error boundary
        logger.exception("step %s failed", name)
        return StepResult(
            name=name,
            status="failed",
            wall_sec=time.monotonic() - t0,
            error=f"{type(exc).__name__}: {exc}",
        )


# ---------------------------------------------------------------------------
# Acquisition steps
# ---------------------------------------------------------------------------

def acquire_rinex(target: date, *, raw_root: Path, overwrite: bool = False) -> StepResult:
    def _do() -> StepResult:
        results = geonet_rinex.fetch(target, raw_root, overwrite=overwrite)
        n_skip = sum(1 for r in results if getattr(r, "skipped", False))
        return StepResult(
            "acquire_rinex",
            "ok" if results else "failed",
            n_total=len(results),
            n_ok=len(results) - n_skip,
            n_skipped=n_skip,
            error=None if results else "no RINEX files returned (data not yet published?)",
        )

    return _guard("acquire_rinex", _do)


def acquire_brdc(target: date, *, raw_root: Path, overwrite: bool = False) -> StepResult:
    def _do() -> StepResult:
        r = cddis_brdc.fetch(target, raw_root, overwrite=overwrite)
        skipped = getattr(r, "skipped", False)
        return StepResult(
            "acquire_brdc",
            "skipped" if skipped else "ok",
            n_total=1,
            n_ok=0 if skipped else 1,
            n_skipped=1 if skipped else 0,
        )

    return _guard("acquire_brdc", _do)


def acquire_l6(target: date, *, raw_root: Path, overwrite: bool = False) -> StepResult:
    def _do() -> StepResult:
        hourly, merged = qzss_l6.fetch(target, raw_root, overwrite=overwrite)
        n_skip = sum(1 for r in hourly if getattr(r, "skipped", False))
        return StepResult(
            "acquire_l6",
            "ok" if merged else "failed",
            n_total=len(hourly),
            n_ok=len(hourly) - n_skip,
            n_skipped=n_skip,
            error=None if merged else "no merged L6 AX produced",
        )

    return _guard("acquire_l6", _do)


# ---------------------------------------------------------------------------
# Processing + QC steps
# ---------------------------------------------------------------------------

def process(
    target: date,
    *,
    mode: str,
    raw_root: Path,
    output_root: Path,
    workers: int | None = None,
    force: bool = False,
) -> StepResult:
    name = f"process:{mode}"

    def _do() -> StepResult:
        _results, summary = claslib_engine.process_doy(
            target,
            mode=mode,
            raw_root=raw_root,
            output_root=output_root,
            max_workers=workers,
            force=force,
        )
        detail: dict[str, Any] = {}
        if summary.failed_stations:
            detail["failed_stations"] = summary.failed_stations[:20]
        return StepResult(
            name,
            status_from_counts(
                summary.n_stations, summary.n_succeeded, summary.n_skipped, summary.n_failed
            ),
            n_total=summary.n_stations,
            n_ok=summary.n_succeeded,
            n_skipped=summary.n_skipped,
            n_failed=summary.n_failed,
            detail=detail,
        )

    return _guard(name, _do)


def qc_teqc(
    target: date,
    *,
    raw_root_rinex: Path,
    output_root: Path,
    workers: int | None = None,
    force: bool = False,
) -> StepResult:
    def _do() -> StepResult:
        res = _teqc.process_doy(
            target,
            raw_root=raw_root_rinex,
            output_root=output_root,
            max_workers=workers,
            force=force,
        )
        detail: dict[str, Any] = {}
        if res.failed_stations:
            detail["failed_stations"] = res.failed_stations[:20]
        return StepResult(
            "qc_teqc",
            status_from_counts(res.n_total, res.n_succeeded, res.n_skipped, res.n_failed),
            n_total=res.n_total,
            n_ok=res.n_succeeded,
            n_skipped=res.n_skipped,
            n_failed=res.n_failed,
            detail=detail,
        )

    return _guard("qc_teqc", _do)


def qc_summarize(target: date, *, input_root: Path, output_root: Path) -> StepResult:
    def _do() -> StepResult:
        res = _summary.summarize_doy(
            target, input_root=input_root, output_root=output_root
        )
        n_ok = res.n_stations - res.n_failed
        return StepResult(
            "qc_summarize",
            status_from_counts(res.n_stations, n_ok, 0, res.n_failed),
            n_total=res.n_stations,
            n_ok=n_ok,
            n_failed=res.n_failed,
            detail={"parquet": str(res.parquet_path)},
        )

    return _guard("qc_summarize", _do)
