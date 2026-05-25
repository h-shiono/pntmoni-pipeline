"""CLASLIB ``rnx2rtkp`` engine wrapper.

Replaces ``run_rnx2rtkp.py`` from gnss_research_toolbox. The legacy
script also handled cold-storage copy + gunzip of BRDC and L6 files;
those concerns are now owned by the acquisition layer, which leaves
ready-to-process artefacts under ``data/raw/``.

Workflow per-DOY
----------------
1. Resolve binary, mode config, and aux data dir.
2. Set up a workspace (binary symlink, ``data/`` symlink, mode config).
3. Decompress the day's BRDC and the next day's BRDC once for the DOY.
4. Symlink the merged L6 (``YYYYDDDAX.l6``).
5. For each station's ``.26o.gz``, in parallel up to ``cpu_count()``:
   - Decompress obs into the workspace.
   - Read receiver/antenna from the obs header.
   - Render a per-station config with substituted ``pos1-rectype`` and
     ``ant1-anttype`` and a SHA-256 hash for provenance.
   - Run ``rnx2rtkp -k {mode}_{station}.conf -ti <interval> ...``.
   - Move ``.pos`` and ``.pos.trace`` to
     ``data/processed/{mode}/{year}/{DOY}/``.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import os
import re
import shutil
import subprocess
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from ..acquisition import igs_atx
from . import _binary, _stats, _workspace
from ._base import ProcessingResult
from ._config import record_station_provenance, write_station_config
from ._obs_header import read_identity
from ._stats import RunSummary, format_summary

logger = logging.getLogger(__name__)

ENGINE = "claslib"
DEFAULT_INTERVAL_SEC = 30

# config keys whose value is a path to an aux data file we want to hash.
_AUX_FILE_KEYS = (
    "file-rcvantfile",
    "file-satantfile",
    "file-eopfile",
    "file-blqfile",
    "file-cssrgridfile",
    "file-isbfile",
    "file-phacycfile",
    "file-dcbfile",
    "file-geoidfile",
)
_AUX_KV_RE = re.compile(r"^\s*(file-[a-z]+)\s*=\s*([^\s#]+)")


def _aux_hashes(mode_template: Path, data_dir: Path) -> dict[str, str]:
    """SHA-256 every aux file referenced by ``mode_template``.

    ``data/...`` references are resolved relative to ``data_dir``
    (matching how rnx2rtkp resolves them inside the workspace).
    """
    hashes: dict[str, str] = {}
    text = mode_template.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        m = _AUX_KV_RE.match(line)
        if not m:
            continue
        key, value = m.group(1), m.group(2)
        if key not in _AUX_FILE_KEYS:
            continue
        # rel paths like ``data/foo.bar`` are resolved against data_dir
        path = Path(value)
        if not path.is_absolute() and value.startswith("data/"):
            path = data_dir / value[len("data/"):]
        if not path.is_file():
            logger.debug("aux hash skip (missing): %s -> %s", key, path)
            continue
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        hashes[key] = h.hexdigest()
    return hashes


# ---------------------------------------------------------------------------
# Path layout
# ---------------------------------------------------------------------------

def rinex_obs_path(raw_root: Path, target: date, station: str) -> Path:
    """Return the canonical .26o.gz path for one station on one DOY."""
    yy = f"{target.year % 100:02d}"
    doy = int(target.strftime("%j"))
    return (
        raw_root / "rinex" / f"{target.year}" / f"{doy:03d}"
        / f"{station}{doy:03d}0.{yy}o.gz"
    )


def list_obs_files(raw_root: Path, target: date) -> list[Path]:
    """All ``.26o.gz`` (or ``.<yy>o.gz``) files acquired for the DOY."""
    yy = f"{target.year % 100:02d}"
    doy = int(target.strftime("%j"))
    pattern = f"*{doy:03d}0.{yy}o.gz"
    return sorted((raw_root / "rinex" / f"{target.year}" / f"{doy:03d}").glob(pattern))


def _brdc_gz(raw_root: Path, target: date) -> Path:
    doy = int(target.strftime("%j"))
    fname = f"BRDC00IGS_R_{target.year}{doy:03d}0000_01D_MN.rnx.gz"
    return raw_root / "brdc" / f"{target.year}" / fname


def _l6_merged(raw_root: Path, target: date) -> Path:
    doy = int(target.strftime("%j"))
    return raw_root / "l6" / f"{target.year}" / f"{doy:03d}" / f"{target.year}{doy:03d}AX.l6"


def output_dir(output_root: Path, mode: str, target: date) -> Path:
    doy = int(target.strftime("%j"))
    return output_root / mode / f"{target.year}" / f"{doy:03d}"


# ---------------------------------------------------------------------------
# Per-station processing
# ---------------------------------------------------------------------------

def _run_rnx2rtkp(
    workspace: Path,
    binary_name: str,
    config_name: str,
    interval: int,
    ts: str,
    te: str,
    obs_rel: str,
    brdc_rel: str,
    brdc_next_rel: str,
    l6_rel: str,
    out_name: str,
) -> None:
    cmd = [
        f"./{binary_name}",
        "-k", config_name,
        "-ti", str(interval),
        "-ts", ts, "-te", te,
        obs_rel, brdc_rel, brdc_next_rel, l6_rel,
        "-x", "1",
        "-o", out_name,
    ]
    logger.info("rnx2rtkp %s", " ".join(cmd[1:]))
    subprocess.run(
        cmd, cwd=workspace,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=True,
    )


def process_station(
    obs_gz: Path,
    *,
    target: date,
    mode: str,
    workspace: Path,
    binary: Path,
    mode_template: Path,
    brdc_in_workspace: Path,
    brdc_next_in_workspace: Path,
    l6_in_workspace: Path,
    output_dir: Path,
    engine_version: str,
    interval: int = DEFAULT_INTERVAL_SEC,
    force: bool = False,
    aux_data_sha256: dict[str, str] | None = None,
    provenance_path: Path | None = None,
) -> ProcessingResult:
    """Run rnx2rtkp on one station's RINEX OBS for one DOY."""
    station = obs_gz.name[:4]
    doy = int(target.strftime("%j"))
    out_name = f"{station}{doy:03d}0.pos"
    pos_dst = output_dir / out_name
    trace_dst = output_dir / f"{out_name}.trace"
    conf_dst = output_dir / f"{mode}_{station}.conf"

    started = datetime.now(UTC)

    if pos_dst.exists() and not force:
        logger.info("found %s — skipping", pos_dst.name)
        finished = datetime.now(UTC)
        return ProcessingResult(
            engine=ENGINE,
            engine_version=engine_version,
            mode=mode,
            config_hash="",
            station=station,
            date=target.isoformat(),
            pos_path=pos_dst,
            trace_path=trace_dst if trace_dst.exists() else None,
            config_path=conf_dst if conf_dst.exists() else None,
            started_at=started,
            finished_at=finished,
            duration_sec=(finished - started).total_seconds(),
            skipped=True,
            metadata={"doy": doy},
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Decompress obs into the workspace.
    obs_in_ws = workspace / obs_gz.name.removesuffix(".gz")
    _workspace.gunzip_to(obs_gz, obs_in_ws, overwrite=force)

    try:
        # 2. Identity from header → 3. per-station config.
        identity = read_identity(obs_in_ws)
        per_station_conf = workspace / f"{mode}_{station}.conf"
        config_hash = write_station_config(mode_template, per_station_conf, identity)

        # 4. Day window in rnx2rtkp's expected format.
        ts = datetime.strptime(
            f"{target.year}{doy:03d}000000", "%Y%j%H%M%S",
        ).strftime("%Y/%m/%d %H:%M:%S")
        te = datetime.strptime(
            f"{target.year}{doy:03d}235959", "%Y%j%H%M%S",
        ).strftime("%Y/%m/%d %H:%M:%S")

        def _rel(p: Path) -> str:
            return os.path.relpath(p, workspace)

        # 5. Invoke rnx2rtkp.
        _run_rnx2rtkp(
            workspace,
            binary_name=binary.name,
            config_name=per_station_conf.name,
            interval=interval,
            ts=ts, te=te,
            obs_rel=_rel(obs_in_ws),
            brdc_rel=_rel(brdc_in_workspace),
            brdc_next_rel=_rel(brdc_next_in_workspace),
            l6_rel=_rel(l6_in_workspace),
            out_name=out_name,
        )

        # 6. Move outputs into the dst tree.
        shutil.move(str(workspace / out_name), pos_dst)
        trace_src = workspace / f"{out_name}.trace"
        if trace_src.exists():
            shutil.move(str(trace_src), trace_dst)
        shutil.move(str(per_station_conf), conf_dst)

        # 7. Cleanup obs and any stray .osr.
        for stray in (obs_in_ws, workspace / f"{out_name}.osr"):
            stray.unlink(missing_ok=True)

        # 8. Per-station provenance row (rectype/anttype/aux hashes).
        record_station_provenance(
            date_iso=target.isoformat(),
            mode=mode,
            station=station,
            identity=identity,
            config_hash=config_hash,
            config_path=conf_dst,
            obs_path=obs_gz,
            template_path=mode_template,
            aux_data_sha256=aux_data_sha256,
            log_path=provenance_path,
        )

    except BaseException:
        # Best-effort cleanup so a partial run does not poison the workspace.
        for leftover in (
            workspace / f"{mode}_{station}.conf",
            workspace / out_name,
            workspace / f"{out_name}.trace",
            obs_in_ws,
        ):
            leftover.unlink(missing_ok=True)
        raise

    finished = datetime.now(UTC)
    return ProcessingResult(
        engine=ENGINE,
        engine_version=engine_version,
        mode=mode,
        config_hash=config_hash,
        station=station,
        date=target.isoformat(),
        pos_path=pos_dst,
        trace_path=trace_dst if trace_dst.exists() else None,
        config_path=conf_dst,
        started_at=started,
        finished_at=finished,
        duration_sec=(finished - started).total_seconds(),
        skipped=False,
        metadata={
            "doy": doy,
            "interval_sec": interval,
            "obs_input": str(obs_gz),
        },
    )


# ---------------------------------------------------------------------------
# DOY-level orchestrator
# ---------------------------------------------------------------------------

def process_doy(
    target: date,
    *,
    mode: str,
    raw_root: Path = Path("data/raw"),
    output_root: Path = Path("data/processed"),
    workspace: Path | None = None,
    binary: Path | None = None,
    data_dir: Path = Path("vendor/pntmoni-claslib/data"),
    config_dir: Path = Path("configs"),
    stations: Iterable[str] | None = None,
    interval: int = DEFAULT_INTERVAL_SEC,
    max_workers: int | None = None,
    force: bool = False,
    stats_path: Path | None = None,
) -> tuple[list[ProcessingResult], RunSummary]:
    """Process every (or a filtered subset of) GEONET station for one DOY.

    Parameters
    ----------
    target : the calendar date.
    mode : config name without ``.conf`` (e.g. ``"kinematic_p30"``).
    stations : optional iterable of 4-char station IDs.
    max_workers : thread pool size (defaults to ``os.cpu_count()``).
    stats_path : where to append the per-run summary JSONL. Defaults to
        ``data/metadata/processing.jsonl`` (set via ``_stats``).

    Returns
    -------
    (results, summary) : ProcessingResults plus an aggregate RunSummary
        whose record was already appended to ``stats_path``.
    """
    started_at = datetime.now(UTC)
    # Guard: the date-based ATX selection only implements the igs20
    # (>= 2022-11-27) branch. Refuse pre-switch dates rather than
    # silently applying the wrong frame (methodology §2.1 / §8.4).
    igs_atx.select_atx_for_date(target)
    binary = binary or _binary.find_binary()
    engine_version = _binary.detect_version(binary)
    mode_template = (config_dir / f"{mode}.conf").resolve()
    if not mode_template.is_file():
        raise FileNotFoundError(f"mode config not found: {mode_template}")

    doy = int(target.strftime("%j"))
    workspace = workspace or Path("data/work") / mode / f"{target.year}" / f"{doy:03d}"
    workspace = workspace.resolve()
    out_dir = output_dir(output_root, mode, target).resolve()

    # Set up workspace once for the whole DOY.
    _workspace.setup(
        workspace,
        binary=binary, data_dir=data_dir.resolve(), mode_config=mode_template,
    )

    # Shared inputs (BRDC of target day + next day, L6 merged).
    brdc_gz = _brdc_gz(raw_root, target)
    next_target = target + timedelta(days=1)
    brdc_next_gz = _brdc_gz(raw_root, next_target)
    l6_src = _l6_merged(raw_root, target)
    for required in (brdc_gz, brdc_next_gz, l6_src):
        if not required.is_file():
            raise FileNotFoundError(f"missing acquisition artefact: {required}")

    brdc_in_ws = _workspace.gunzip_to(brdc_gz, workspace / brdc_gz.stem)
    brdc_next_in_ws = _workspace.gunzip_to(brdc_next_gz, workspace / brdc_next_gz.stem)
    l6_in_ws = workspace / l6_src.name
    if l6_in_ws.is_symlink() or l6_in_ws.exists():
        l6_in_ws.unlink()
    try:
        os.symlink(l6_src.resolve(), l6_in_ws)
    except OSError:
        shutil.copy2(l6_src, l6_in_ws)

    # Station list.
    if stations is None:
        obs_files = list_obs_files(raw_root, target)
    else:
        obs_files = [
            rinex_obs_path(raw_root, target, s) for s in stations
        ]
        obs_files = [p for p in obs_files if p.is_file()]
    if not obs_files:
        logger.warning("no obs files matched for %s", target.isoformat())
        finished_at = datetime.now(UTC)
        empty_summary = _stats.summarize(
            [], failed_stations=[],
            started_at=started_at, finished_at=finished_at,
            engine=ENGINE, engine_version=engine_version, mode=mode,
            date_iso=target.isoformat(),
        )
        _stats.record(empty_summary, path=stats_path)
        return [], empty_summary

    workers = max_workers or os.cpu_count() or 1
    aux_sha256 = _aux_hashes(mode_template, data_dir.resolve())
    logger.info(
        "processing %d station(s) for %s with %d workers (mode=%s, engine=%s, aux_files=%d)",
        len(obs_files), target.isoformat(), workers, mode, engine_version, len(aux_sha256),
    )
    for key, h in aux_sha256.items():
        logger.info("aux %s sha256=%s", key, h[:16])

    results: list[ProcessingResult] = []
    failed_stations: list[str] = []
    with _workspace.cleanup_partials(workspace):
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {
                ex.submit(
                    process_station,
                    obs,
                    target=target, mode=mode,
                    workspace=workspace,
                    binary=binary,
                    mode_template=workspace / mode_template.name,
                    brdc_in_workspace=brdc_in_ws,
                    brdc_next_in_workspace=brdc_next_in_ws,
                    l6_in_workspace=l6_in_ws,
                    output_dir=out_dir,
                    engine_version=engine_version,
                    interval=interval,
                    force=force,
                    aux_data_sha256=aux_sha256,
                ): obs for obs in obs_files
            }
            for fut in concurrent.futures.as_completed(futures):
                obs = futures[fut]
                try:
                    results.append(fut.result())
                except Exception as exc:
                    logger.error(
                        "station %s failed: %s: %s",
                        obs.name[:4], type(exc).__name__, exc,
                    )
                    failed_stations.append(obs.name[:4])

    finished_at = datetime.now(UTC)
    summary = _stats.summarize(
        results,
        failed_stations=failed_stations,
        started_at=started_at,
        finished_at=finished_at,
        engine=ENGINE,
        engine_version=engine_version,
        mode=mode,
        date_iso=target.isoformat(),
    )
    # Tier 1: human-readable log line(s).
    for line in format_summary(summary).splitlines():
        logger.info(line)
    # Tier 2: append run record for trend tracking.
    _stats.record(summary, path=stats_path)

    return results, summary
