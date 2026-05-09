"""DOY-level QC summary roll-up: walk teqc ``.{yy}S`` → wide Parquet.

One Parquet per (date) under
``data/processed/qc_summary/{year}/{YYYYMMDD}.parquet`` with one row
per station and the same wide column ordering as the legacy
``summary.csv``. Provenance columns ``date``, ``source_file``, and
``generated_at`` are appended for audit.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from . import _summary_parser

logger = logging.getLogger(__name__)

DEFAULT_INPUT_ROOT = Path("data/processed/qc_teqc")
DEFAULT_OUTPUT_ROOT = Path("data/processed/qc_summary")
DEFAULT_PROVENANCE_PATH = Path("data/metadata/qc_summary.jsonl")


@dataclass(frozen=True)
class QCSummaryResult:
    target_date: date
    parquet_path: Path
    n_stations: int
    n_failed: int


def list_summary_files(input_root: Path, target: date) -> list[Path]:
    yy = f"{target.year % 100:02d}"
    doy = int(target.strftime("%j"))
    return sorted(
        (input_root / f"{target.year}" / f"{doy:03d}").glob(f"*0.{yy}S")
    )


def output_path(output_root: Path, target: date) -> Path:
    return output_root / f"{target.year}" / f"{target.strftime('%Y%m%d')}.parquet"


def summarize_doy(
    target: date,
    *,
    input_root: Path = DEFAULT_INPUT_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    record_provenance: bool = True,
    provenance_path: Path | None = None,
) -> QCSummaryResult:
    """Parse every ``.{yy}S`` for ``target`` and write a single Parquet."""
    summary_files = list_summary_files(input_root, target)
    if not summary_files:
        raise FileNotFoundError(
            f"no .{target.year % 100:02d}S files for {target} under "
            f"{input_root}; run `pntmoni-pipeline qc teqc` first"
        )

    rows: list[dict] = []
    n_failed = 0
    failed_paths: list[str] = []
    for sf in summary_files:
        try:
            parsed = _summary_parser.parse_teqc_summary(sf)
        except Exception as exc:                              # pragma: no cover
            n_failed += 1
            failed_paths.append(sf.name)
            logger.warning("parse failed for %s: %s: %s", sf.name, type(exc).__name__, exc)
            continue
        row = _summary_parser.to_wide_row(parsed)
        row["date"] = target.isoformat()
        row["source_file"] = sf.name
        rows.append(row)

    if not rows:
        raise RuntimeError(f"no parseable .S files for {target}")

    cols = (
        _summary_parser.wide_columns()
        + ["date", "source_file"]
    )
    df = pd.DataFrame(rows, columns=cols)
    out = output_path(output_root, target)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)

    result = QCSummaryResult(
        target_date=target,
        parquet_path=out,
        n_stations=len(rows),
        n_failed=n_failed,
    )
    logger.info(
        "qc summary: wrote %s (%d stations, %d failed)",
        out, result.n_stations, result.n_failed,
    )
    if record_provenance:
        _record(result, failed_paths, provenance_path or DEFAULT_PROVENANCE_PATH)
    return result


def _record(res: QCSummaryResult, failed: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "target_date": res.target_date.isoformat(),
        "tool": "summarize_qc",
        "n_stations": res.n_stations,
        "n_failed": res.n_failed,
        "failed_files": failed[:50],
        "parquet_path": str(res.parquet_path),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


__all__ = [
    "DEFAULT_INPUT_ROOT",
    "DEFAULT_OUTPUT_ROOT",
    "QCSummaryResult",
    "list_summary_files",
    "output_path",
    "summarize_doy",
]
