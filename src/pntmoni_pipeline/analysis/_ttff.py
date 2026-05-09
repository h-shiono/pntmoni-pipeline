"""Time-To-First-Fix (TTFF) extraction from CLASLIB ``.pos`` output.

Per ADR 0005, PNT Moni measures TTFF on PPP-RTK with periodic filter
resets enabled (``misc-regularly``). Phase 0 uses the 15-minute
primary period (``misc-regularly = 900``); a 60-minute secondary
period is added in Phase 1 for cross-service comparison.

Mechanics
---------
With ``misc-regularly = R`` and sampling interval ``ti``, the filter
resets every ``R`` seconds → ``R/ti`` epochs per "reset window".
Within each window, the filter re-converges through Q=1 (single)
→ Q=5 (RTK float) → Q=4 (RTK fix). TTFF is the time from the
window's first epoch to the first epoch with Q=4.

If the filter does not reach Q=4 within a window, TTFF is reported
as ``None`` and counted as an unfixed window in the summary.

The very first window (window_idx=0) measures cold-start TTFF; later
windows measure post-reset TTFF. Both are included in the summary
because both correspond to user-visible "time to usable position".
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_RESET_PERIOD_SEC = 900       # ADR 0005 primary
DEFAULT_SAMPLING_INTERVAL_SEC = 30   # 30s GEONET data
DEFAULT_TTFF_PATH = Path("data/metadata/ttff.jsonl")
DEFAULT_LEAP_SECONDS = 18            # GPST − UTC as of 2026; hard-update at next leap
SECONDS_PER_DAY = 86_400
NMEA_Q_FIX = 4                       # see CLASLIB solq_nmea[]
NMEA_Q_FLOAT = 5

_GPGGA_RE = re.compile(
    r"^\$GPGGA,(\d{2})(\d{2})(\d{2})(?:\.\d+)?,[^,]*,[^,]*,[^,]*,[^,]*,(\d),"
)
_MISC_REGULARLY_RE = re.compile(r"^\s*misc-regularly\s*=\s*(\d+)")


@dataclass(frozen=True)
class TTFFEvent:
    window_idx: int
    reset_epoch_idx: int
    fixed_epoch_idx: int | None
    ttff_sec: float | None
    n_epochs_to_fix: int | None

    @property
    def fixed(self) -> bool:
        return self.fixed_epoch_idx is not None


@dataclass(frozen=True)
class TTFFSummary:
    station: str
    date: str
    mode: str
    reset_period_sec: int
    sampling_interval_sec: int
    n_windows: int
    n_fixed: int
    n_unfixed: int
    fix_success_rate: float          # 0..1
    ttff_p50_sec: float              # only over fixed windows
    ttff_p95_sec: float
    ttff_max_sec: float
    ttff_min_sec: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_jsonable(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# .pos parsing
# ---------------------------------------------------------------------------

def parse_pos_quality(pos_path: Path) -> list[int]:
    """Return one NMEA quality flag per ``$GPGGA`` line, in file order.

    Convenience for callers that don't need TOW alignment (e.g. for
    QC histograms over all epochs in a file). For TTFF extraction use
    :func:`parse_pos_epochs` instead — it returns a sparse epoch map
    that survives observation gaps.
    """
    out: list[int] = []
    with pos_path.open("r") as f:
        for line in f:
            m = _GPGGA_RE.match(line)
            if m:
                out.append(int(m.group(4)))
    return out


def parse_pos_epochs(
    pos_path: Path,
    *,
    sampling_interval_sec: int = DEFAULT_SAMPLING_INTERVAL_SEC,
    leap_seconds: int = DEFAULT_LEAP_SECONDS,
) -> dict[int, int]:
    """Return ``{epoch_idx_of_day: Q}`` keyed by GPST-day-aligned epoch.

    NMEA timestamps are UTC; GPST = UTC + ``leap_seconds`` (currently
    18). The "epoch index of day" = ``GPST_sec_of_day // ti``, so a 30 s
    full day yields indices 0..2879 regardless of in-file order or
    missing observations. This is the alignment ``misc-regularly`` uses
    after MOD-001 (TOW-modulo reset), so window boundaries are stable
    across observation gaps.
    """
    if SECONDS_PER_DAY % sampling_interval_sec:
        raise ValueError(
            f"sampling_interval_sec={sampling_interval_sec} must divide 86400"
        )
    epochs: dict[int, int] = {}
    with pos_path.open("r") as f:
        for line in f:
            m = _GPGGA_RE.match(line)
            if not m:
                continue
            hh, mm, ss, q = m.groups()
            utc_sod = int(hh) * 3600 + int(mm) * 60 + int(ss)
            gpst_sod = (utc_sod + leap_seconds) % SECONDS_PER_DAY
            epoch_idx = gpst_sod // sampling_interval_sec
            epochs[epoch_idx] = int(q)
    return epochs


def detect_reset_period_from_config(conf_path: Path) -> int | None:
    """Read ``misc-regularly`` from a CLASLIB ``.conf`` file (None if absent)."""
    try:
        with conf_path.open("r") as f:
            for line in f:
                m = _MISC_REGULARLY_RE.match(line)
                if m:
                    return int(m.group(1))
    except OSError:
        return None
    return None


# ---------------------------------------------------------------------------
# Event extraction + summary
# ---------------------------------------------------------------------------

def extract_events(
    epochs: dict[int, int] | list[int],
    *,
    reset_period_sec: int,
    sampling_interval_sec: int,
    n_windows: int | None = None,
) -> Iterator[TTFFEvent]:
    """Yield one :class:`TTFFEvent` per reset window.

    A window covers epoch indices ``[w * R/ti, (w+1) * R/ti)``. TTFF is
    measured from the window's first epoch index to the first epoch
    with ``Q == 4`` within it. Returns ``ttff_sec=None`` for windows
    that don't reach a fix (or that have no observations at all).

    ``epochs`` accepts either:
    - ``dict[int, int]`` mapping ``epoch_idx_of_day → Q`` (preferred —
      tolerates observation gaps; obtainable from
      :func:`parse_pos_epochs`), or
    - ``list[int]`` of consecutive Q values starting at index 0
      (legacy — used by tests and full-coverage runs).

    ``n_windows`` defaults to the number needed to cover the highest
    observed epoch. Pass an explicit value (e.g. 96 for a full day with
    R=900s) to also account for trailing windows with no observations.
    """
    if reset_period_sec <= 0 or sampling_interval_sec <= 0:
        raise ValueError("reset_period_sec and sampling_interval_sec must be > 0")
    if reset_period_sec % sampling_interval_sec:
        raise ValueError(
            f"reset_period_sec ({reset_period_sec}) must be a multiple of "
            f"sampling_interval_sec ({sampling_interval_sec})"
        )
    epochs_per_window = reset_period_sec // sampling_interval_sec

    if isinstance(epochs, list):
        epochs = {i: q for i, q in enumerate(epochs)}
    if not isinstance(epochs, dict):
        raise TypeError("epochs must be dict[int, int] or list[int]")

    if n_windows is None:
        if epochs:
            max_epoch = max(epochs)
            n_windows = max_epoch // epochs_per_window + 1
        else:
            n_windows = 0

    for w in range(n_windows):
        start = w * epochs_per_window
        end = start + epochs_per_window
        fixed_epoch: int | None = None
        for j in range(start, end):
            q = epochs.get(j)
            if q == NMEA_Q_FIX:
                fixed_epoch = j
                break
        if fixed_epoch is None:
            yield TTFFEvent(
                window_idx=w,
                reset_epoch_idx=start,
                fixed_epoch_idx=None,
                ttff_sec=None,
                n_epochs_to_fix=None,
            )
        else:
            n_eps = fixed_epoch - start
            yield TTFFEvent(
                window_idx=w,
                reset_epoch_idx=start,
                fixed_epoch_idx=fixed_epoch,
                ttff_sec=float(n_eps * sampling_interval_sec),
                n_epochs_to_fix=n_eps,
            )


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if p <= 0:
        return s[0]
    if p >= 100:
        return s[-1]
    k = (len(s) - 1) * p / 100
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def summarize(
    events: Iterable[TTFFEvent],
    *,
    station: str,
    date: str,
    mode: str,
    reset_period_sec: int,
    sampling_interval_sec: int,
    metadata: dict[str, Any] | None = None,
) -> TTFFSummary:
    events = list(events)
    fixed = [e.ttff_sec for e in events if e.ttff_sec is not None]
    n_windows = len(events)
    n_fixed = len(fixed)
    n_unfixed = n_windows - n_fixed
    return TTFFSummary(
        station=station,
        date=date,
        mode=mode,
        reset_period_sec=reset_period_sec,
        sampling_interval_sec=sampling_interval_sec,
        n_windows=n_windows,
        n_fixed=n_fixed,
        n_unfixed=n_unfixed,
        fix_success_rate=(n_fixed / n_windows) if n_windows else 0.0,
        ttff_p50_sec=_percentile(fixed, 50),
        ttff_p95_sec=_percentile(fixed, 95),
        ttff_max_sec=max(fixed) if fixed else 0.0,
        ttff_min_sec=min(fixed) if fixed else 0.0,
        metadata=metadata or {},
    )


def record(summary: TTFFSummary, path: Path | None = None) -> Path:
    out = path or DEFAULT_TTFF_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary.to_jsonable(), ensure_ascii=False) + "\n")
    return out


def format_summary(s: TTFFSummary) -> str:
    return (
        f"{s.station} {s.date} mode={s.mode} reset={s.reset_period_sec}s ti={s.sampling_interval_sec}s "
        f"windows={s.n_windows} fixed={s.n_fixed} ({100*s.fix_success_rate:.1f}%) "
        f"TTFF p50={s.ttff_p50_sec:.0f}s p95={s.ttff_p95_sec:.0f}s max={s.ttff_max_sec:.0f}s"
    )


# ---------------------------------------------------------------------------
# DOY-level analyzer (walks data/processed/{mode}/{year}/{doy}/)
# ---------------------------------------------------------------------------

def analyze_doy(
    target_date_iso: str,
    *,
    mode: str,
    output_root: Path = Path("data/processed"),
    stations: Iterable[str] | None = None,
    reset_period_sec: int | None = None,
    sampling_interval_sec: int = DEFAULT_SAMPLING_INTERVAL_SEC,
    record_path: Path | None = None,
) -> list[TTFFSummary]:
    """Compute TTFF summaries for every (or selected) station's .pos.

    Auto-detects ``reset_period_sec`` from the per-station ``.conf``
    saved alongside each ``.pos`` if the parameter is None.
    """
    from datetime import date as _date
    target = _date.fromisoformat(target_date_iso)
    doy = int(target.strftime("%j"))
    doy_dir = output_root / mode / f"{target.year}" / f"{doy:03d}"
    if not doy_dir.is_dir():
        raise FileNotFoundError(f"no processed output at {doy_dir}")

    pos_paths = sorted(doy_dir.glob("*.pos"))
    if stations is not None:
        wanted = set(stations)
        pos_paths = [p for p in pos_paths if p.name[:4] in wanted]

    summaries: list[TTFFSummary] = []
    for pos in pos_paths:
        station = pos.name[:4]
        conf_path = pos.parent / f"{mode}_{station}.conf"
        period = reset_period_sec or detect_reset_period_from_config(conf_path)
        if period is None:
            logger.warning(
                "no misc-regularly in %s and no --reset-period given; skipping %s",
                conf_path, station,
            )
            continue
        epoch_map = parse_pos_epochs(
            pos, sampling_interval_sec=sampling_interval_sec,
        )
        n_windows = SECONDS_PER_DAY // period   # full-day expectation
        events = list(extract_events(
            epoch_map,
            reset_period_sec=period,
            sampling_interval_sec=sampling_interval_sec,
            n_windows=n_windows,
        ))
        s = summarize(
            events,
            station=station,
            date=target_date_iso,
            mode=mode,
            reset_period_sec=period,
            sampling_interval_sec=sampling_interval_sec,
            metadata={
                "pos_path": str(pos),
                "n_observed_epochs": len(epoch_map),
            },
        )
        record(s, path=record_path)
        summaries.append(s)
    return summaries


__all__ = [
    "DEFAULT_RESET_PERIOD_SEC",
    "DEFAULT_SAMPLING_INTERVAL_SEC",
    "DEFAULT_TTFF_PATH",
    "TTFFEvent",
    "TTFFSummary",
    "analyze_doy",
    "detect_reset_period_from_config",
    "extract_events",
    "format_summary",
    "parse_pos_quality",
    "record",
    "summarize",
]
