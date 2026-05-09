"""teqc-driven QC summary (.{yy}S) from GEONET RINEX 3 inputs.

End-to-end pipeline per (date, station):

    1. Decompress ``data/raw/rinex/{year}/{doy}/{station}{doy}0.{yy}o.gz``
    2. Untar  ``                          ...{station}{doy}0.{yy}N.tar.gz``
       → ``.{yy}n``, ``.{yy}l``, ``.{yy}q`` (and ``.{yy}g`` GLONASS,
       which is dropped — the official methodology in
       gnss_research_toolbox/eval_geonet.py excludes GLONASS)
    3. Run RTKLIB ``convbin`` four times (one per input format) into
       isolated subdirs to avoid output-name collisions; move the
       relevant ``.obs``/``.nav``/``.lnav``/``.qnav`` to the per-station
       working dir.
    4. Rewrite ``.lnav`` → ``.gal`` and ``.qnav`` → ``.qzs`` with
       teqc-compatible RINEX 2 headers (see :mod:`_nav_rewrite`).
    5. Run teqc under Rosetta 2 (``arch -x86_64``):
       ``teqc -R +L2C_L2 +L5 +qc -nav nav,gal,qzs <obs>``
    6. Move the produced ``.{yy}S`` summary to the canonical output
       path under ``data/processed/qc_teqc/{year}/{doy}/``.

Defaults expect ``vendor/teqc/{teqc, convbin}`` to be staged.
``teqc`` is the upstream Intel macOS binary (Rosetta 2 must be
installed on Apple Silicon hosts). ``convbin`` is the RTKLIB
``app/convbin/gcc/`` build (native arm64 on Apple Silicon).
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from . import _nav_rewrite

logger = logging.getLogger(__name__)

DEFAULT_RAW_RINEX_ROOT = Path("data/raw/rinex")
DEFAULT_OUTPUT_ROOT = Path("data/processed/qc_teqc")
DEFAULT_TEQC = Path("vendor/teqc/teqc")
DEFAULT_CONVBIN = Path("vendor/teqc/convbin")
DEFAULT_PROVENANCE_PATH = Path("data/metadata/qc_teqc.jsonl")

CONVBIN_BASE_ARGS = ("-r", "rinex", "-f", "5", "-od", "-os", "-oi", "-ot", "-ol", "-y", "R")
TEQC_QC_ARGS = ("-R", "+L2C_L2", "+L5", "+qc")


@dataclass(frozen=True)
class StationQCResult:
    station: str
    target_date: date
    summary_path: Path | None       # None if processing failed
    duration_sec: float
    error: str | None = None        # short error description on failure


@dataclass(frozen=True)
class DOYQCResult:
    target_date: date
    n_total: int
    n_succeeded: int
    n_failed: int
    n_skipped: int
    wall_sec: float
    output_dir: Path
    teqc_binary: Path
    convbin_binary: Path
    failed_stations: list[str]


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _gunzip_to(src_gz: Path, dst: Path) -> None:
    import gzip
    import shutil
    with gzip.open(src_gz, "rb") as fin, dst.open("wb") as fout:
        shutil.copyfileobj(fin, fout, length=1024 * 1024)


def _untar_nav_archive(tar_gz: Path, dst_dir: Path) -> None:
    """Extract a ``{station}{doy}0.{yy}N.tar.gz`` into ``dst_dir``."""
    with tarfile.open(tar_gz, "r:gz") as tar:
        tar.extractall(dst_dir, filter="data")


def _run_convbin(
    convbin: Path, source_path: Path, out_dir: Path,
) -> subprocess.CompletedProcess:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(convbin), *CONVBIN_BASE_ARGS, "-d", str(out_dir), str(source_path)]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)


def _run_teqc(
    teqc: Path, work_dir: Path, obs_name: str, nav_files: list[str],
) -> subprocess.CompletedProcess:
    """Invoke teqc under Rosetta 2 (``arch -x86_64``) on macOS arm64.

    ``arch`` resolves its first non-option argument as an executable
    via ``$PATH`` only — relative paths are NOT looked up against the
    caller's cwd. We always pass the binary as an absolute path so the
    caller can stage ``teqc`` anywhere.
    """
    nav_arg = ",".join(nav_files)
    teqc_abs = str(teqc.resolve())
    base_cmd = [teqc_abs, *TEQC_QC_ARGS, "-nav", nav_arg, obs_name]
    cmd: list[str] = (
        ["arch", "-x86_64", *base_cmd] if sys.platform == "darwin" else base_cmd
    )
    return subprocess.run(
        cmd, cwd=work_dir, capture_output=True, text=True, check=False, timeout=300,
    )


def station_id_from_obs(obs_path: Path) -> str:
    """Extract the 4-char station code from a GEONET RINEX OBS filename."""
    return obs_path.name[:4]


def doy_dir(raw_root: Path, target: date) -> Path:
    doy = int(target.strftime("%j"))
    return raw_root / f"{target.year}" / f"{doy:03d}"


def output_dir(output_root: Path, target: date) -> Path:
    doy = int(target.strftime("%j"))
    return output_root / f"{target.year}" / f"{doy:03d}"


def expected_summary_path(output_root: Path, target: date, station: str) -> Path:
    yy = f"{target.year % 100:02d}"
    doy = int(target.strftime("%j"))
    return output_dir(output_root, target) / f"{station}{doy:03d}0.{yy}S"


def list_obs_files(raw_root: Path, target: date) -> list[Path]:
    yy = f"{target.year % 100:02d}"
    doy = int(target.strftime("%j"))
    pattern = f"*{doy:03d}0.{yy}o.gz"
    return sorted(doy_dir(raw_root, target).glob(pattern))


# ---------------------------------------------------------------------------
# Per-station pipeline
# ---------------------------------------------------------------------------

def process_station(
    obs_gz: Path,
    *,
    target: date,
    raw_root: Path,
    output_root: Path,
    teqc: Path,
    convbin: Path,
    force: bool = False,
) -> StationQCResult:
    """Run the full QC pipeline for one station; return the summary path."""
    started = time.time()
    station = station_id_from_obs(obs_gz)
    out_dir = output_dir(output_root, target)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = expected_summary_path(output_root, target, station)

    if summary_path.is_file() and not force:
        return StationQCResult(
            station=station, target_date=target,
            summary_path=summary_path,
            duration_sec=time.time() - started,
        )

    yy = f"{target.year % 100:02d}"
    doy = int(target.strftime("%j"))
    base_name = f"{station}{doy:03d}0"
    nav_tar_gz = doy_dir(raw_root, target) / f"{base_name}.{yy}N.tar.gz"
    if not nav_tar_gz.is_file():
        return StationQCResult(
            station=station, target_date=target,
            summary_path=None, duration_sec=time.time() - started,
            error=f"missing nav archive: {nav_tar_gz}",
        )

    try:
        with tempfile.TemporaryDirectory(prefix="qc_teqc_") as tmp_str:
            work = Path(tmp_str)
            # Step 1+2: decompress.
            obs_v3 = work / f"{base_name}.{yy}o"
            _gunzip_to(obs_gz, obs_v3)
            _untar_nav_archive(nav_tar_gz, work)
            (work / f"{base_name}.{yy}g").unlink(missing_ok=True)  # GLONASS dropped

            # Step 3: convbin → v2 (each input into its own subdir to avoid
            # cross-format output name collisions on the temp tree).
            for src_ext, out_ext in (
                (f"{yy}o", "obs"),
                (f"{yy}n", "nav"),
                (f"{yy}l", "lnav"),
                (f"{yy}q", "qnav"),
            ):
                src_file = work / f"{base_name}.{src_ext}"
                if not src_file.is_file():
                    continue
                conv_out = work / f"conv_{src_ext}"
                proc = _run_convbin(convbin, src_file, conv_out)
                if proc.returncode != 0:
                    return StationQCResult(
                        station=station, target_date=target,
                        summary_path=None, duration_sec=time.time() - started,
                        error=f"convbin {src_ext} failed: {proc.stderr.strip()[:240]}",
                    )
                produced = conv_out / f"{base_name}.{out_ext}"
                if produced.is_file():
                    produced.rename(work / produced.name)

            # Step 4: rewrite Galileo / QZSS NAV headers for teqc.
            if (work / f"{base_name}.lnav").is_file():
                _nav_rewrite.rewrite_lnav_to_gal(
                    work / f"{base_name}.lnav", work / f"{base_name}.gal",
                )
            if (work / f"{base_name}.qnav").is_file():
                _nav_rewrite.rewrite_qnav_to_qzs(
                    work / f"{base_name}.qnav", work / f"{base_name}.qzs",
                )

            # Step 5: teqc.
            obs_v2 = work / f"{base_name}.obs"
            if not obs_v2.is_file():
                return StationQCResult(
                    station=station, target_date=target,
                    summary_path=None, duration_sec=time.time() - started,
                    error="convbin did not produce a v2 OBS file",
                )
            nav_files: list[str] = []
            for ext in ("nav", "gal", "qzs"):
                if (work / f"{base_name}.{ext}").is_file():
                    nav_files.append(f"{base_name}.{ext}")
            if not nav_files:
                return StationQCResult(
                    station=station, target_date=target,
                    summary_path=None, duration_sec=time.time() - started,
                    error="no nav files available for teqc",
                )
            proc = _run_teqc(teqc, work, obs_v2.name, nav_files)
            if proc.returncode != 0:
                return StationQCResult(
                    station=station, target_date=target,
                    summary_path=None, duration_sec=time.time() - started,
                    error=f"teqc failed: {proc.stderr.strip()[:240]}",
                )

            # Step 6: move the .{yy}S summary into the canonical output dir.
            produced_summary = work / f"{base_name}.{yy}S"
            if not produced_summary.is_file():
                return StationQCResult(
                    station=station, target_date=target,
                    summary_path=None, duration_sec=time.time() - started,
                    error=f"teqc did not produce {produced_summary.name}",
                )
            produced_summary.rename(summary_path)

    except Exception as exc:                                # pragma: no cover
        return StationQCResult(
            station=station, target_date=target,
            summary_path=None, duration_sec=time.time() - started,
            error=f"{type(exc).__name__}: {exc!s}"[:240],
        )

    return StationQCResult(
        station=station, target_date=target,
        summary_path=summary_path,
        duration_sec=time.time() - started,
    )


# ---------------------------------------------------------------------------
# DOY-level driver
# ---------------------------------------------------------------------------

def process_doy(
    target: date,
    *,
    raw_root: Path = DEFAULT_RAW_RINEX_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    teqc: Path = DEFAULT_TEQC,
    convbin: Path = DEFAULT_CONVBIN,
    stations: Iterable[str] | None = None,
    max_workers: int | None = None,
    force: bool = False,
    record_provenance: bool = True,
    provenance_path: Path | None = None,
) -> DOYQCResult:
    """Run teqc QC on every (or filtered) station for one DOY."""
    if not teqc.is_file():
        raise FileNotFoundError(
            f"teqc binary not at {teqc}; place the macOS Intel binary "
            f"(e.g. ``teqc_OSX_i5_gcc4.3d_64.zip``) under vendor/teqc/"
        )
    if not convbin.is_file():
        raise FileNotFoundError(
            f"convbin binary not at {convbin}; build via "
            f"`gcc *.o -lm -o convbin` in RTKLIB/app/convbin/gcc/"
        )

    obs_paths = list_obs_files(raw_root, target)
    if stations is not None:
        wanted = set(stations)
        obs_paths = [p for p in obs_paths if station_id_from_obs(p) in wanted]
    if not obs_paths:
        raise FileNotFoundError(
            f"no .{target.year % 100:02d}o.gz files for {target} under {raw_root}"
        )

    workers = max_workers or os.cpu_count() or 1
    started = time.time()
    logger.info(
        "qc teqc: %d stations for %s with %d workers (teqc=%s convbin=%s)",
        len(obs_paths), target.isoformat(), workers, teqc, convbin,
    )

    results: list[StationQCResult] = []
    failed_stations: list[str] = []
    n_skipped = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(
                process_station,
                obs,
                target=target, raw_root=raw_root, output_root=output_root,
                teqc=teqc, convbin=convbin, force=force,
            ): obs for obs in obs_paths
        }
        for fut in concurrent.futures.as_completed(futures):
            obs = futures[fut]
            try:
                r = fut.result()
            except Exception as exc:                        # pragma: no cover
                station = station_id_from_obs(obs)
                failed_stations.append(station)
                logger.error(
                    "station %s exception: %s: %s", station, type(exc).__name__, exc,
                )
                continue
            results.append(r)
            if r.error is not None:
                failed_stations.append(r.station)
                logger.warning("station %s failed: %s", r.station, r.error)

    n_total = len(obs_paths)
    n_succeeded = sum(1 for r in results if r.error is None and r.summary_path)
    # "Skipped" = pre-existing summary, evidenced by very short duration.
    # A more reliable signal: result.error is None AND duration_sec < 0.05.
    n_skipped = sum(
        1 for r in results
        if r.error is None and r.summary_path and r.duration_sec < 0.05
    )
    n_failed = len(failed_stations)
    wall = time.time() - started

    out_dir = output_dir(output_root, target)
    result = DOYQCResult(
        target_date=target,
        n_total=n_total,
        n_succeeded=n_succeeded,
        n_failed=n_failed,
        n_skipped=n_skipped,
        wall_sec=wall,
        output_dir=out_dir,
        teqc_binary=teqc,
        convbin_binary=convbin,
        failed_stations=failed_stations,
    )
    logger.info(
        "qc teqc done: %d/%d succeeded (%d skipped, %d failed) in %.1f s",
        n_succeeded, n_total, n_skipped, n_failed, wall,
    )
    if record_provenance:
        _record_provenance(result, provenance_path or DEFAULT_PROVENANCE_PATH)
    return result


def _record_provenance(res: DOYQCResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "target_date": res.target_date.isoformat(),
        "tool": "teqc",
        "n_total": res.n_total,
        "n_succeeded": res.n_succeeded,
        "n_failed": res.n_failed,
        "n_skipped": res.n_skipped,
        "wall_sec": res.wall_sec,
        "output_dir": str(res.output_dir),
        "teqc_binary": str(res.teqc_binary),
        "convbin_binary": str(res.convbin_binary),
        "failed_stations": res.failed_stations[:50],
        "generated_at": datetime.now(UTC).isoformat(),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


__all__ = [
    "CONVBIN_BASE_ARGS",
    "DEFAULT_CONVBIN",
    "DEFAULT_OUTPUT_ROOT",
    "DEFAULT_RAW_RINEX_ROOT",
    "DEFAULT_TEQC",
    "DOYQCResult",
    "StationQCResult",
    "TEQC_QC_ARGS",
    "expected_summary_path",
    "list_obs_files",
    "process_doy",
    "process_station",
    "station_id_from_obs",
]
