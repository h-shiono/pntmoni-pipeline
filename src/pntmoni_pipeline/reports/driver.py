"""Drive the monthly Quarto report end-to-end.

Pipeline:
  1. Gather monthly Parquet inputs (accuracy / TTFF / L6 alerts).
  2. Compute the §7.2 pipeline ``config_hash`` over the period's config
     set + engine / QC / reference-coord / methodology version strings;
     record the full digest to ``processing.jsonl`` (§7.3).
  3. Assemble Quarto params (period, stream, version strings, the
     16-char ``config_hash`` display, parquet input paths).
  4. Optionally invoke ``quarto render --execute-params`` against
     ``reports/templates/monthly.qmd``.

The template's binding to these params (replacing the synthetic
placeholder data with real loads) is the next sub-step tracked in
``tasks/todo.md``; until then a render produces a report still based
on the qmd's defaults, but the params file and the provenance record
are correct and reproducible.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .. import config_hash as _ch
from ..analysis import _reference_coords

logger = logging.getLogger(__name__)

# Authoritative version strings (methodology §3.1 / §6 / §7.2).
QC_TOOL_NAME = "teqc"
QC_TOOL_VERSION = "2019Feb25"
QC_TOOL_FULL = f"{QC_TOOL_NAME} {QC_TOOL_VERSION}"
METHODOLOGY_VERSION = "1.0.0"
ENGINE_NAME = "pntmoni-claslib"
DEFAULT_ENGINE_VERSION = "v0.8.3-pntmoni-1"   # asserted by methodology §3.1

DEFAULT_TEMPLATE = Path("reports/templates/monthly_free.qmd")
DEFAULT_OUTPUT_ROOT = Path("data/reports")
DEFAULT_PROCESSING_LOG = Path("data/metadata/processing.jsonl")
DEFAULT_CONFIG_DIR = Path("configs")


# --- Inputs --------------------------------------------------------------

@dataclass
class InputsBundle:
    """Loaded monthly inputs (``None`` when not yet produced)."""

    period: str
    mode: str
    accuracy_station: pd.DataFrame | None = None
    accuracy_network: pd.DataFrame | None = None
    ttff_station: pd.DataFrame | None = None
    ttff_network: pd.DataFrame | None = None
    l6_alerts: pd.DataFrame | None = None
    paths: dict[str, Path] = field(default_factory=dict)

    def status(self) -> dict[str, str]:
        return {
            k: ("present" if getattr(self, k) is not None else "missing")
            for k in (
                "accuracy_station", "accuracy_network",
                "ttff_station", "ttff_network", "l6_alerts",
            )
        }


def _read_if_present(p: Path) -> pd.DataFrame | None:
    if p.is_file():
        return pd.read_parquet(p)
    logger.debug("input missing (ok): %s", p)
    return None


def _ttff_mode_for(mode: str) -> str:
    """Map an accuracy mode → the matching TTFF measurement mode.

    Accuracy is computed in the continuous mode (e.g.
    ``kinematic_p30_verify``); TTFF needs periodic resets per
    methodology §5.2 and is processed in a paired ``_ttff_verify``
    mode (e.g. ``kinematic_p30_ttff_verify``). Continuous-mode TTFF
    numbers exist in the parquet but are mostly 0 s (fix at first
    epoch) — they would mislead readers if surfaced as "TTFF".
    """
    if "_ttff" in mode:
        return mode
    return mode.replace("_verify", "_ttff_verify")


def gather_inputs(
    period: str,
    mode: str,
    *,
    processed_root: Path = Path("data/processed"),
    ttff_mode: str | None = None,
) -> InputsBundle:
    """Load monthly parquets for ``(period, mode)``; missing → None.

    ``ttff_mode`` controls which mode's TTFF parquets are loaded.
    Defaults to ``_ttff_mode_for(mode)`` so TTFF figures pick up the
    paired reset-measurement mode automatically.
    """
    if len(period) != 7 or period[4] != "-":
        raise ValueError(f"period must be YYYY-MM, got {period!r}")
    yyyymm = period.replace("-", "")
    year = int(period[:4])
    sub = f"{mode}/{year}/{yyyymm}.parquet"
    ttff_mode = ttff_mode or _ttff_mode_for(mode)
    ttff_sub = f"{ttff_mode}/{year}/{yyyymm}.parquet"

    paths = {
        "accuracy_station":  processed_root / "accuracy_monthly"         / sub,
        "accuracy_network":  processed_root / "accuracy_network_monthly" / sub,
        "ttff_station":      processed_root / "ttff_monthly"             / ttff_sub,
        "ttff_network":      processed_root / "ttff_network_monthly"     / ttff_sub,
        "l6_alerts":         processed_root / "l6_alerts" / f"{year}" / f"{period}.parquet",
    }
    bundle = InputsBundle(period=period, mode=mode, paths=paths)
    for k, p in paths.items():
        setattr(bundle, k, _read_if_present(p))
    # Directory-style inputs (passed through to INPUTS but not loaded
    # into the bundle DataFrame fields). epoch_errors is per-day and
    # too large for a single read; the qmd streams + subsamples it.
    # reference_coords_dir provides station ECEF coords used by the
    # hex-grid spatial figure (analysis/_hex_grid.py).
    bundle.paths["epoch_errors_dir"] = processed_root / "epoch_errors" / mode
    bundle.paths["reference_coords_dir"] = processed_root / "reference_coords"
    # NAGU / NANU / NAQU satellite outage events (acquired via
    # `acquire satellite-outages`). Single events.parquet that holds
    # all history; qmd filters to the reporting period.
    bundle.paths["satellite_outages"] = (
        processed_root / "satellite_outages" / "events.parquet"
    )
    return bundle


# --- config_hash for a monthly run --------------------------------------

def default_config_inputs(
    *, config_dir: Path = DEFAULT_CONFIG_DIR, mode: str,
) -> tuple[list[Path], list[Path]]:
    """Return the (TOML, .conf) inputs that define a monthly run.

    Toml = the acquisition + station + jumps registries. Conf = the
    CLASLIB processing config for ``mode`` (e.g. ``kinematic_p30_verify``).
    Caller can override; this default mirrors a typical monthly batch.
    """
    tomls = sorted(config_dir.glob("*.toml")) + sorted((config_dir / "stations").glob("*.toml"))
    confs = [config_dir / f"{mode}.conf"]
    confs = [p for p in confs if p.is_file()]
    return tomls, confs


def compute_monthly_config_hash(
    *, mode: str, engine_version: str = DEFAULT_ENGINE_VERSION,
    config_dir: Path = DEFAULT_CONFIG_DIR,
) -> _ch.ConfigHashResult:
    """Wrap :func:`config_hash.compute_config_hash` for the monthly run."""
    tomls, confs = default_config_inputs(config_dir=config_dir, mode=mode)
    return _ch.compute_config_hash(
        engine_version=f"{ENGINE_NAME} {engine_version}",
        qc_tool_version=QC_TOOL_FULL,
        reference_coord_version=_reference_coords.METHODOLOGY_VERSION,
        methodology_version=METHODOLOGY_VERSION,
        toml_paths=tomls, conf_paths=confs,
    )


# --- Params + render ----------------------------------------------------

def assemble_params(
    *,
    period: str,
    mode: str,
    stream: str,
    inputs: InputsBundle,
    config_hash_full: str,
    engine_version: str = DEFAULT_ENGINE_VERSION,
    data_mode: str = "live",
) -> dict[str, Any]:
    """Build the Quarto params dict for the monthly template (§7.4 tag)."""
    year = int(period[:4])
    month = int(period[5:7])
    return {
        "year": year,
        "month": month,
        "period": period,
        "stream": stream,
        "mode": mode,
        "methodology_version": METHODOLOGY_VERSION,
        "config_hash": config_hash_full[: _ch.DISPLAY_LEN],
        "config_hash_full": config_hash_full,
        "engine": ENGINE_NAME,
        "engine_version": engine_version,
        "qc_tool": QC_TOOL_NAME,
        "qc_version": QC_TOOL_VERSION,
        "reference_coord_version": _reference_coords.METHODOLOGY_VERSION,
        "data_mode": data_mode,
        # Parquet input paths — absolute so the qmd reads them
        # regardless of Quarto's render cwd (which is the qmd's dir).
        "inputs": {k: str(p.resolve()) for k, p in inputs.paths.items()},
        "inputs_status": inputs.status(),
    }


def render(
    template: Path,
    params: dict[str, Any],
    output_dir: Path,
    *,
    formats: tuple[str, ...] = ("html", "pdf"),
) -> dict[str, Path]:
    """Render the Quarto template with ``params``; return output paths.

    Requires ``quarto`` on PATH. Params are passed to the qmd via the
    ``PNTMONI_REPORT_PARAMS`` env var pointing at a JSON file; the qmd's
    parameters cell reads it (see ``reports/templates/monthly.qmd``).
    Quarto's own ``--execute-params`` / ``-P`` mechanism is intentionally
    not used here — it does not reliably inject overrides into the
    Jupyter-tagged cell in current Quarto builds.
    """
    if not shutil.which("quarto"):
        raise RuntimeError(
            "`quarto` not found on PATH. Install Quarto CLI: https://quarto.org/"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    template = template.resolve()
    params_path = output_dir / "params.json"
    params_path.write_text(
        json.dumps(params, default=str, indent=2), encoding="utf-8",
    )
    env = {**os.environ, "PNTMONI_REPORT_PARAMS": str(params_path.resolve())}
    out: dict[str, Path] = {}
    for fmt in formats:
        cmd = [
            "quarto", "render", str(template),
            "--to", fmt,
            "--output-dir", str(output_dir.resolve()),
            # The Jupyter execute-daemon caches a kernel across renders;
            # its env is the env of the first render, so subsequent
            # PNTMONI_REPORT_PARAMS values are ignored. Disable it.
            "--no-execute-daemon",
        ]
        logger.info("quarto render --to %s (PNTMONI_REPORT_PARAMS=%s)", fmt, params_path)
        subprocess.run(cmd, check=True, env=env)
        ext = "html" if fmt == "html" else "pdf"
        # Quarto may place the output under a subdir matching the qmd's
        # parent (e.g. <out>/templates/monthly.html) when --output-dir
        # is set; find the actual file rather than assume the flat path.
        produced = list(output_dir.rglob(f"{template.stem}.{ext}"))
        if not produced:
            raise RuntimeError(f"Quarto produced no {ext} under {output_dir}")
        out[fmt] = produced[0]
    return out


# --- Orchestration + provenance -----------------------------------------

@dataclass
class RunResult:
    period: str
    mode: str
    stream: str
    config_hash_full: str
    config_hash_display: str
    inputs_status: dict[str, str]
    params_path: Path
    outputs: dict[str, Path] = field(default_factory=dict)
    rendered: bool = False
    generated_at: str = ""


def _record_processing_provenance(
    result: RunResult, log_path: Path,
) -> Path:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "kind": "report_monthly",
        "period": result.period,
        "mode": result.mode,
        "stream": result.stream,
        "config_hash_full": result.config_hash_full,
        "config_hash_display": result.config_hash_display,
        "inputs_status": result.inputs_status,
        "params_path": str(result.params_path),
        "outputs": {k: str(v) for k, v in result.outputs.items()},
        "rendered": result.rendered,
        "generated_at": result.generated_at,
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return log_path


def run_monthly(
    *,
    period: str,
    mode: str,
    stream: str,
    engine_version: str = DEFAULT_ENGINE_VERSION,
    data_mode: str = "live",
    template: Path = DEFAULT_TEMPLATE,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    processing_log: Path = DEFAULT_PROCESSING_LOG,
    processed_root: Path = Path("data/processed"),
    config_dir: Path = DEFAULT_CONFIG_DIR,
    do_render: bool = False,
    formats: tuple[str, ...] = ("html", "pdf"),
) -> RunResult:
    """Gather inputs, compute config_hash, assemble params, optionally render."""
    inputs = gather_inputs(period, mode, processed_root=processed_root)
    ch = compute_monthly_config_hash(
        mode=mode, engine_version=engine_version, config_dir=config_dir,
    )
    params = assemble_params(
        period=period, mode=mode, stream=stream, inputs=inputs,
        config_hash_full=ch.full, engine_version=engine_version, data_mode=data_mode,
    )
    out_dir = output_root / stream / period
    out_dir.mkdir(parents=True, exist_ok=True)
    params_path = out_dir / "params.json"
    params_path.write_text(json.dumps(params, default=str, indent=2), encoding="utf-8")

    outputs: dict[str, Path] = {}
    rendered = False
    if do_render:
        outputs = render(template, params, out_dir, formats=formats)
        rendered = True
    else:
        logger.info("render skipped (--render not set); params written to %s", params_path)

    result = RunResult(
        period=period, mode=mode, stream=stream,
        config_hash_full=ch.full,
        config_hash_display=ch.full[: _ch.DISPLAY_LEN],
        inputs_status=inputs.status(),
        params_path=params_path,
        outputs=outputs, rendered=rendered,
        generated_at=datetime.now(UTC).isoformat(),
    )
    _record_processing_provenance(result, processing_log)
    return result
