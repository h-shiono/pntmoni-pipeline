#!/usr/bin/env python3
"""One-shot migration of gnss_research_toolbox/clas_eval/* CSVs into TOML.

Three TOML files are produced under ``configs/stations/``:

    network_assignments.toml   netid + isinside per station (from latest year)
    network_info.toml          4-grid CLAS info per station (from latest year)
    eval_periods.toml          per-station list of eval-point periods (from
                               all available service_performance/fy*_*_h.csv)

Cross-year consistency is checked and warned about (e.g. when netid for a
station differs between years). The TOMLs include a provenance header
recording the legacy source path and the legacy repo URL — see
``pntmoni-docs`` for the gnss_research_toolbox repo reference.

Run once:

    uv run scripts/migrate_legacy_station_data.py \\
        --legacy-root /Users/hayato/dev/gnss_research_toolbox/clas_eval \\
        --output-dir configs/stations

The script does not consume from the legacy data again at runtime — it
purely produces the TOMLs that pipeline modules read.
"""
from __future__ import annotations

import argparse
import csv
import io
import logging
import subprocess
import textwrap
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

LEGACY_REPO_URL = "https://github.com/h-shiono/gnss_research_toolbox"


def _parse_date(s: str | None) -> date | None:
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    return date.fromisoformat(s.replace("/", "-"))


def _parse_optional_int(s: str | None) -> int | None:
    if s is None:
        return None
    s = s.strip()
    if not s or s.lower() == "nan":
        return None
    return int(float(s))


def _toml_string(s: str) -> str:
    """Render ``s`` as a basic TOML string (double-quoted, escapes)."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _toml_key(s: str) -> str:
    """Quote a TOML key. We always quote station IDs to avoid edge cases."""
    return _toml_string(s)


def _open_csv_skip_blank_header(path: Path) -> io.StringIO:
    """Read ``path`` skipping any leading blank lines before the header.

    fy2021_1st_h.csv ships with a stray ``\\n`` before its header line; if we
    feed that to ``csv.DictReader`` the empty line becomes the fieldnames
    and every row reads as ``{'': '...'}``. Strip leading blanks first.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    while lines and not lines[0].strip():
        lines.pop(0)
    return io.StringIO("".join(lines))


def _legacy_git_sha(repo_root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or None
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return None


# ---------------------------------------------------------------------------
# fy*_*_h.csv → eval_periods
# ---------------------------------------------------------------------------

def _gather_eval_periods(
    service_performance_dir: Path,
) -> tuple[dict[str, list[dict]], list[Path]]:
    """Read every fy*_*_h.csv (eval-point list) and group by station ID."""
    fy_csvs = [
        p for p in sorted(service_performance_dir.glob("fy*_*_h.csv"))
        if "_perf_" not in p.name
    ]
    eval_periods: dict[str, list[dict]] = defaultdict(list)
    for fy_csv in fy_csvs:
        fy_label = fy_csv.stem  # e.g. "fy2024_1st_h"
        reader = csv.DictReader(_open_csv_skip_blank_header(fy_csv))
        n_rows = 0
        for row in reader:
            rinex_id = (row.get("id") or "").strip()
            if not rinex_id:
                continue
            n_rows += 1
            eval_periods[rinex_id].append({
                "from": _parse_date(row.get("from")),
                "to": _parse_date(row.get("to")),
                "fy_label": fy_label,
                "netid": _parse_optional_int(row.get("nid") or row.get("netid")),
            })
        logger.debug("fy_csv=%s rows=%d", fy_csv.name, n_rows)
    # Sort each station's periods by `from`.
    for stations in eval_periods.values():
        stations.sort(key=lambda r: (r["from"] or date.min, r["fy_label"]))
    return eval_periods, fy_csvs


def _write_eval_periods_toml(
    eval_periods: dict[str, list[dict]],
    out_path: Path,
    *,
    fy_csvs: list[Path],
    legacy_root: Path,
    legacy_sha: str | None,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    src_list = "\n".join(f"#   - {p.relative_to(legacy_root)}" for p in fy_csvs)
    header = textwrap.dedent(f"""\
        # configs/stations/eval_periods.toml
        # CLAS Official evaluation point periods (per QSS Performance Report).
        # Each station has zero or more periods. ``is_eval(rinex_id, target_date)``
        # is True iff any period satisfies ``from <= target_date <= to``.
        #
        # Updates: typically once per fiscal half (Apr-Sep / Oct-Mar) but custom
        # periods can appear when stations are decommissioned mid-period or
        # earthquakes cause crustal motion temporary disqualification.
        # See tasks/lessons.md for management protocol.
        #
        # Auto-generated by scripts/migrate_legacy_station_data.py
        # Source legacy repo: {LEGACY_REPO_URL}
        # Source legacy commit: {legacy_sha or "(unknown)"}
        # Source files (under {legacy_root}):
        {src_list}
        # Generated: {datetime.now(UTC).isoformat()}
        # Stations covered: {len(eval_periods)}
        """)
    lines = [header]
    for rinex_id in sorted(eval_periods):
        periods = eval_periods[rinex_id]
        if not periods:
            continue
        lines.append(f"[stations.{_toml_key(rinex_id)}]")
        lines.append("periods = [")
        for p in periods:
            f_ = p["from"].isoformat() if p["from"] else "1970-01-01"
            t_ = p["to"].isoformat() if p["to"] else "9999-12-31"
            lbl = _toml_string(p["fy_label"])
            netid_kv = f", netid = {p['netid']}" if p["netid"] is not None else ""
            lines.append(f"    {{ from = {f_}, to = {t_}, fy_label = {lbl}{netid_kv} }},")
        lines.append("]")
        lines.append("")
    out_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# station_ng.csv → network_assignments
# ---------------------------------------------------------------------------

def _gather_network_assignments(
    legacy_root: Path,
) -> tuple[dict[str, dict], list[tuple[str, list[tuple[int, int | None]]]], Path]:
    """Read station_ng.csv from every year, return (latest_state, netid_history, source).

    ``latest_state``: ``{rinex_id: {"netid": int|None, "isinside": bool}}``
        from the most recent year that has ``station_ng.csv``.
    ``netid_history``: list of ``(rinex_id, [(year, netid), ...])`` for stations
        whose netid changed over the years (audit hint, not written to TOML).
    """
    year_dirs = sorted(
        (p for p in legacy_root.iterdir()
         if p.is_dir() and p.name.isdigit() and len(p.name) == 4),
        key=lambda p: int(p.name),
    )
    by_year_state: dict[int, dict[str, dict]] = {}
    for ydir in year_dirs:
        ng = ydir / "station_ng.csv"
        if not ng.is_file():
            continue
        rows: dict[str, dict] = {}
        with ng.open() as f:
            for row in csv.DictReader(f):
                rid = (row.get("id") or "").strip()
                if not rid:
                    continue
                rows[rid] = {
                    "netid": _parse_optional_int(row.get("netid")),
                    "isinside": (row.get("isinside") or "").strip().lower() == "true",
                }
        by_year_state[int(ydir.name)] = rows

    if not by_year_state:
        raise RuntimeError("no station_ng.csv found in any year directory under "
                           f"{legacy_root}")

    latest_year = max(by_year_state)
    latest_state = by_year_state[latest_year]
    source = legacy_root / f"{latest_year}" / "station_ng.csv"

    # Audit: did netid change for any station across years?
    netid_history: list[tuple[str, list[tuple[int, int | None]]]] = []
    all_ids = set().union(*(rs.keys() for rs in by_year_state.values()))
    for rid in sorted(all_ids):
        history = [(y, by_year_state[y].get(rid, {}).get("netid"))
                   for y in sorted(by_year_state)]
        # Keep only stations whose netid actually changed (ignoring None years).
        seen = {n for _, n in history if n is not None}
        if len(seen) > 1:
            netid_history.append((rid, history))

    return latest_state, netid_history, source


def _write_network_assignments_toml(
    state: dict[str, dict],
    out_path: Path,
    *,
    source: Path,
    legacy_root: Path,
    legacy_sha: str | None,
    netid_changes: list[tuple[str, list[tuple[int, int | None]]]],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    audit = ""
    if netid_changes:
        audit_rows = "\n".join(
            f"#   {rid}: " + ", ".join(f"{y}={n}" for y, n in hist)
            for rid, hist in netid_changes[:20]
        )
        audit = textwrap.dedent(f"""\
            # Cross-year netid changes detected (audit, not enforced):
            {audit_rows}
            """)
        if len(netid_changes) > 20:
            audit += f"#   ... and {len(netid_changes) - 20} more.\n"
    header = textwrap.dedent(f"""\
        # configs/stations/network_assignments.toml
        # CLAS network membership (netid 1..12) and inside-coverage flag per
        # GEONET station. Source of truth: latest year's station_ng.csv from the
        # legacy clas_eval archive. Updated only when new GEONET stations are
        # added (see tasks/todo.md station-registry task).
        #
        # Auto-generated by scripts/migrate_legacy_station_data.py
        # Source legacy repo: {LEGACY_REPO_URL}
        # Source legacy commit: {legacy_sha or "(unknown)"}
        # Source file: {source.relative_to(legacy_root)}
        # Generated: {datetime.now(UTC).isoformat()}
        # Stations: {len(state)}
        {audit}""")
    lines = [header]
    for rid in sorted(state):
        v = state[rid]
        lines.append(f"[stations.{_toml_key(rid)}]")
        if v["netid"] is not None:
            lines.append(f"netid = {v['netid']}")
        lines.append(f"isinside = {str(v['isinside']).lower()}")
        lines.append("")
    out_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# station_network_info.csv → network_info
# ---------------------------------------------------------------------------

def _gather_network_info(legacy_root: Path) -> tuple[dict[str, dict], Path]:
    """Read station_network_info.csv (latest year) → 4-grid info per station."""
    year_dirs = sorted(
        (p for p in legacy_root.iterdir()
         if p.is_dir() and p.name.isdigit() and len(p.name) == 4),
        key=lambda p: int(p.name),
        reverse=True,
    )
    info: dict[str, dict] = {}
    source: Path | None = None
    for ydir in year_dirs:
        cand = ydir / "station_network_info.csv"
        if cand.is_file():
            source = cand
            with cand.open() as f:
                for row in csv.DictReader(f):
                    rid = (row.get("id") or "").strip()
                    if not rid:
                        continue
                    grids = []
                    for n in (1, 2, 3, 4):
                        inet_raw = (row.get(f"inet_{n}") or "").strip()
                        if not inet_raw or inet_raw.lower() == "nan":
                            continue
                        try:
                            grid = {
                                "inet": _parse_optional_int(inet_raw),
                                "weight": float(row[f"weight_{n}"]),
                                "lat": float(row[f"lat_{n}"]),
                                "lon": float(row[f"lon_{n}"]),
                                "dist_km": float(row[f"dist_{n}"]),
                                "index": _parse_optional_int(row[f"index_{n}"]),
                            }
                        except (ValueError, TypeError):
                            # Defensive: a partial row where some numeric
                            # field is "nan"; skip this grid slot.
                            continue
                        grids.append(grid)
                    info[rid] = {
                        "n_grids": _parse_optional_int(row.get("n_grids")),
                        "grids": grids,
                    }
            break
    if source is None:
        raise RuntimeError(f"no station_network_info.csv under {legacy_root}/{{year}}/")
    return info, source


def _write_network_info_toml(
    info: dict[str, dict],
    out_path: Path,
    *,
    source: Path,
    legacy_root: Path,
    legacy_sha: str | None,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = textwrap.dedent(f"""\
        # configs/stations/network_info.toml
        # CLAS correction-grid weighting per GEONET station, derived from
        # CLASLIB debug trace output (top-4 grid points per station with
        # their weights, lat/lon, distance, and index). Stable per station;
        # update only when a new station is added.
        #
        # Auto-generated by scripts/migrate_legacy_station_data.py
        # Source legacy repo: {LEGACY_REPO_URL}
        # Source legacy commit: {legacy_sha or "(unknown)"}
        # Source file: {source.relative_to(legacy_root)}
        # Generated: {datetime.now(UTC).isoformat()}
        # Stations: {len(info)}
        """)
    lines = [header]
    for rid in sorted(info):
        v = info[rid]
        lines.append(f"[stations.{_toml_key(rid)}]")
        if v["n_grids"] is not None:
            lines.append(f"n_grids = {v['n_grids']}")
        lines.append("grids = [")
        for g in v["grids"]:
            inet = g["inet"]
            idx = g["index"]
            lines.append(
                f"    {{ inet = {inet}, weight = {g['weight']:.4f}, "
                f"lat = {g['lat']:.4f}, lon = {g['lon']:.4f}, "
                f"dist_km = {g['dist_km']:.4f}, index = {idx} }},"
            )
        lines.append("]")
        lines.append("")
    out_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--legacy-root", type=Path, required=True,
        help="Path to gnss_research_toolbox/clas_eval/",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("configs/stations"),
        help="Destination directory for the 3 TOML files.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    legacy_root: Path = args.legacy_root.resolve()
    output_dir: Path = args.output_dir.resolve()
    if not legacy_root.is_dir():
        raise SystemExit(f"--legacy-root not found: {legacy_root}")
    legacy_sha = _legacy_git_sha(legacy_root.parent)

    logger.info("legacy_root=%s legacy_sha=%s", legacy_root, legacy_sha)

    # 1. eval_periods
    eval_periods, fy_csvs = _gather_eval_periods(legacy_root / "service_performance")
    logger.info(
        "eval_periods: %d stations from %d fy_*_h CSVs",
        len(eval_periods), len(fy_csvs),
    )
    _write_eval_periods_toml(
        eval_periods,
        output_dir / "eval_periods.toml",
        fy_csvs=fy_csvs,
        legacy_root=legacy_root,
        legacy_sha=legacy_sha,
    )

    # 2. network_assignments
    network_state, netid_changes, ng_source = _gather_network_assignments(legacy_root)
    logger.info(
        "network_assignments: %d stations from %s; %d netid changes across years",
        len(network_state), ng_source.relative_to(legacy_root), len(netid_changes),
    )
    if netid_changes:
        for rid, hist in netid_changes[:5]:
            logger.warning("netid history for %s: %s", rid, hist)
        if len(netid_changes) > 5:
            logger.warning("... and %d more", len(netid_changes) - 5)
    _write_network_assignments_toml(
        network_state,
        output_dir / "network_assignments.toml",
        source=ng_source, legacy_root=legacy_root, legacy_sha=legacy_sha,
        netid_changes=netid_changes,
    )

    # 3. network_info
    network_info, ni_source = _gather_network_info(legacy_root)
    logger.info(
        "network_info: %d stations from %s",
        len(network_info), ni_source.relative_to(legacy_root),
    )
    _write_network_info_toml(
        network_info,
        output_dir / "network_info.toml",
        source=ni_source, legacy_root=legacy_root, legacy_sha=legacy_sha,
    )

    logger.info("done — wrote 3 TOMLs under %s", output_dir)


if __name__ == "__main__":
    main()
