"""Daily per-DOY driver: acquire → process → QC.

``run_day`` runs the per-DOY chain in dependency order, isolates failures
(continue-on-error), and appends one structured record to
``data/metadata/orchestration.jsonl``. Report generation is intentionally
out of scope.

Dependency order::

    acquire {rinex, brdc, l6}
        → process claslib (× modes)   # both consume RINEX
        → qc teqc                      # consumes RINEX
            → qc summarize             # consumes teqc output

``process`` and ``qc teqc`` run sequentially (not concurrently) because
each already saturates the CPU via its own per-station thread pool.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from ..processing import claslib_engine
from ..qc import _summary
from . import _steps
from ._steps import StepResult

logger = logging.getLogger(__name__)

#: Production positioning modes (accuracy + TTFF twins, per ADR 0013).
DEFAULT_MODES: tuple[str, ...] = (
    "kinematic_p30_verify",
    "kinematic_p30_ttff_verify",
)

DEFAULT_RAW_ROOT = Path("data/raw")
DEFAULT_OUTPUT_ROOT = Path("data/processed")
DEFAULT_QC_TEQC_ROOT = Path("data/processed/qc_teqc")
DEFAULT_QC_SUMMARY_ROOT = Path("data/processed/qc_summary")
DEFAULT_RECORD_PATH = Path("data/metadata/orchestration.jsonl")


@dataclass
class DayResult:
    target: date
    steps: list[StepResult]
    status: str
    started_at: datetime
    finished_at: datetime
    wall_sec: float

    def to_jsonable(self) -> dict:
        return {
            "kind": "daily",
            "date": self.target.isoformat(),
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "wall_sec": round(self.wall_sec, 2),
            "steps": [s.to_jsonable() for s in self.steps],
        }


def _overall_status(steps: list[StepResult]) -> str:
    statuses = {s.status for s in steps}
    if statuses <= {"ok", "skipped"}:
        return "ok"
    if any(s.status in ("ok", "partial") for s in steps):
        return "partial"
    return "failed"


def is_day_complete(
    target: date,
    *,
    modes: tuple[str, ...],
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    qc_summary_root: Path = DEFAULT_QC_SUMMARY_ROOT,
) -> bool:
    """Cheap day-level short-circuit check.

    A day counts as complete when the QC-summary Parquet exists and each
    requested mode's processing output directory holds at least one
    ``.pos``. This avoids re-scanning ~1300 stations per mode when a day
    was already processed; ``--force`` bypasses it.
    """
    if not _summary.output_path(qc_summary_root, target).is_file():
        return False
    for mode in modes:
        d = claslib_engine.output_dir(output_root, mode, target)
        if not d.is_dir() or not any(d.glob("*.pos")):
            return False
    return True


def _record(record_path: Path, result: DayResult) -> None:
    try:
        record_path.parent.mkdir(parents=True, exist_ok=True)
        with record_path.open("a") as f:
            f.write(json.dumps(result.to_jsonable()) + "\n")
    except Exception:  # noqa: BLE001 — provenance must never crash the run
        logger.exception("failed to append orchestration record to %s", record_path)


def run_day(
    target: date,
    *,
    modes: tuple[str, ...] = DEFAULT_MODES,
    skip_acquire: bool = False,
    force: bool = False,
    workers: int | None = None,
    raw_root: Path = DEFAULT_RAW_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    qc_teqc_root: Path = DEFAULT_QC_TEQC_ROOT,
    qc_summary_root: Path = DEFAULT_QC_SUMMARY_ROOT,
    record_path: Path | None = DEFAULT_RECORD_PATH,
) -> DayResult:
    """Run the full per-DOY chain for ``target``."""
    started_at = datetime.now(UTC)
    t0 = time.monotonic()
    steps: list[StepResult] = []

    def _finish() -> DayResult:
        res = DayResult(
            target=target,
            steps=steps,
            status=_overall_status(steps),
            started_at=started_at,
            finished_at=datetime.now(UTC),
            wall_sec=time.monotonic() - t0,
        )
        if record_path is not None:
            _record(record_path, res)
        logger.info(
            "daily %s → %s (%.1fs)", target.isoformat(), res.status, res.wall_sec
        )
        return res

    if not force and is_day_complete(
        target, modes=modes, output_root=output_root, qc_summary_root=qc_summary_root
    ):
        logger.info(
            "%s already complete; skipping (use --force to re-run)", target.isoformat()
        )
        steps.append(
            StepResult("day", "skipped", detail={"reason": "already complete"})
        )
        return _finish()

    # --- Acquisition (overwrite never tied to --force: re-downloading the
    #     ~7 GB/day archive is wasteful; the fetchers already skip-if-exists).
    rinex_ok = True
    if skip_acquire:
        logger.info("skip-acquire: assuming RINEX/BRDC/L6 already present")
    else:
        rinex = _steps.acquire_rinex(target, raw_root=raw_root)
        steps.append(rinex)
        steps.append(_steps.acquire_brdc(target, raw_root=raw_root))
        steps.append(_steps.acquire_l6(target, raw_root=raw_root))
        rinex_ok = not rinex.failed

    if not rinex_ok:
        reason = {"reason": "rinex acquire failed — cannot process"}
        for mode in modes:
            steps.append(StepResult(f"process:{mode}", "skipped", detail=reason))
        steps.append(StepResult("qc_teqc", "skipped", detail=reason))
        steps.append(StepResult("qc_summarize", "skipped", detail=reason))
        return _finish()

    # --- Positioning (one step per mode).
    for mode in modes:
        steps.append(
            _steps.process(
                target,
                mode=mode,
                raw_root=raw_root,
                output_root=output_root,
                workers=workers,
                force=force,
            )
        )

    # --- QC (teqc → summarize).
    teqc = _steps.qc_teqc(
        target,
        raw_root_rinex=raw_root / "rinex",
        output_root=qc_teqc_root,
        workers=workers,
        force=force,
    )
    steps.append(teqc)
    if teqc.failed:
        steps.append(
            StepResult(
                "qc_summarize", "skipped", detail={"reason": "qc_teqc failed"}
            )
        )
    else:
        steps.append(
            _steps.qc_summarize(
                target, input_root=qc_teqc_root, output_root=qc_summary_root
            )
        )

    return _finish()
