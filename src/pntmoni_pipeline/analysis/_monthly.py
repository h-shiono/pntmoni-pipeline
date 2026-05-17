"""Stage 2 monthly roll-up: re-aggregate daily epoch_errors over a month.

Percentiles cannot be averaged across days; for an exact monthly metric
we re-pool every day's epoch_errors and recompute. The roll-up modules
keep the daily Parquets canonical and produce monthly Parquets only on
demand (e.g. for monthly reports).

Outputs land alongside the daily Parquets:

    accuracy_monthly/{mode}/{year}/{YYYYMM}.parquet
    accuracy_network_monthly/{mode}/{year}/{YYYYMM}.parquet
    ttff_monthly/{mode}/{year}/{YYYYMM}.parquet
    ttff_network_monthly/{mode}/{year}/{YYYYMM}.parquet

Rows in the monthly outputs are keyed by ``period`` (= ``"YYYY-MM"``)
rather than ``date``; everything else mirrors the daily schema.
"""
from __future__ import annotations

import calendar
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from . import _accuracy_stats, _coords_math, _registry, _ttff_stats

logger = logging.getLogger(__name__)

DEFAULT_PROVENANCE_PATH = Path("data/metadata/monthly_rollup.jsonl")


@dataclass(frozen=True)
class MonthlyRollupResult:
    period: str             # "YYYY-MM"
    mode: str
    engine_version: str
    accuracy_station: Path
    accuracy_network: Path
    ttff_station: Path
    ttff_network: Path
    n_dates_pooled: int


def _dates_in_month(year: int, month: int) -> list[date]:
    last = calendar.monthrange(year, month)[1]
    return [date(year, month, d) for d in range(1, last + 1)]


def _read_available_epoch_errors(
    period_dates: list[date],
    mode: str,
    epoch_errors_root: Path,
) -> tuple[pd.DataFrame, list[date]]:
    """Concat every epoch_errors Parquet that exists for the period."""
    frames = []
    found: list[date] = []
    for d in period_dates:
        p = _accuracy_stats.epoch_errors_path(d, mode, epoch_errors_root)
        if p.is_file():
            frames.append(pd.read_parquet(p))
            found.append(d)
    if not frames:
        return pd.DataFrame(), []
    return pd.concat(frames, ignore_index=True), found


def compute_monthly(
    year: int,
    month: int,
    *,
    mode: str,
    engine_version: str = "unknown",
    epoch_errors_root: Path = _accuracy_stats.DEFAULT_EPOCH_ERRORS_ROOT,
    output_root: Path = _accuracy_stats.DEFAULT_OUTPUT_ROOT,
    reset_period_sec: int = _ttff_stats.DEFAULT_RESET_PERIOD_SEC,
    sampling_interval_sec: int = _ttff_stats.DEFAULT_SAMPLING_INTERVAL_SEC,
    horizontal_threshold_m: float | None = None,
    vertical_threshold_m: float | None = None,
    min_window_completion: float = _ttff_stats.DEFAULT_MIN_WINDOW_COMPLETION,
    registry_sources: _registry.RegistrySources | None = None,
    qualification_path: Path | None = None,
    record_provenance: bool = True,
) -> MonthlyRollupResult:
    """Pool every available daily epoch_errors in (year, month) and
    re-run Stage-2a + Stage-2b on the pooled DataFrame.

    The registry is loaded at the *last* found date, since eval_periods
    may shift mid-month; a future revision can break the month into
    eval-period sub-windows if needed.
    """
    if horizontal_threshold_m is None or vertical_threshold_m is None:
        thr = _coords_math.thresholds_for_mode(mode)
        if horizontal_threshold_m is None:
            horizontal_threshold_m = thr.horizontal_m
        if vertical_threshold_m is None:
            vertical_threshold_m = thr.vertical_m

    period_dates = _dates_in_month(year, month)
    epoch_errors, found = _read_available_epoch_errors(
        period_dates, mode, epoch_errors_root,
    )
    if epoch_errors.empty:
        raise FileNotFoundError(
            f"no epoch_errors Parquets in {year}-{month:02d} for mode={mode}; "
            f"run Stage-1 first"
        )
    if "engine_version" in epoch_errors.columns:
        v = epoch_errors["engine_version"].iloc[0]
        if isinstance(v, str) and v:
            engine_version = v

    period_label = f"{year}-{month:02d}"
    last_date = found[-1]
    registry = _registry.load(
        last_date, sources=registry_sources, qualification_path=qualification_path,
    )

    # Stage-2a accuracy on pooled epochs.
    accuracy_station = _accuracy_stats.compute_station_accuracy(
        epoch_errors,
        target_date=last_date, mode=mode, engine_version=engine_version,
    )
    accuracy_station["date"] = period_label  # overwrite to "YYYY-MM"
    accuracy_station = accuracy_station.rename(columns={"date": "period"})

    accuracy_network = _accuracy_stats.compute_network_accuracy(
        epoch_errors, registry,
        target_date=last_date, mode=mode, engine_version=engine_version,
    )
    accuracy_network["date"] = period_label
    accuracy_network = accuracy_network.rename(columns={"date": "period"})

    # Stage-2b TTFF on pooled epochs.
    ttff_station, events = _ttff_stats.compute_station_ttff(
        epoch_errors,
        target_date=last_date, mode=mode, engine_version=engine_version,
        reset_period_sec=reset_period_sec,
        sampling_interval_sec=sampling_interval_sec,
        horizontal_threshold_m=horizontal_threshold_m,
        vertical_threshold_m=vertical_threshold_m,
        min_window_completion=min_window_completion,
    )
    ttff_station["date"] = period_label
    ttff_station = ttff_station.rename(columns={"date": "period"})

    epochs_per_window = reset_period_sec // sampling_interval_sec
    n_windows_per_day = (24 * 3600) // reset_period_sec
    expected_epochs_full_day = n_windows_per_day * epochs_per_window
    expected_epochs_full_period = expected_epochs_full_day * len(found)
    completion_by_station = {
        s: int(grp.shape[0]) / expected_epochs_full_period
        for s, grp in epoch_errors.groupby("station", sort=False)
    }

    ttff_network = _ttff_stats.compute_network_ttff(
        events, registry, completion_by_station,
        target_date=last_date, mode=mode, engine_version=engine_version,
        reset_period_sec=reset_period_sec,
        min_window_completion=min_window_completion,
    )
    ttff_network["date"] = period_label
    ttff_network = ttff_network.rename(columns={"date": "period"})

    suffix = f"{mode}/{year}/{period_label.replace('-', '')}.parquet"
    out_paths = {
        "accuracy_station": output_root / "accuracy_monthly" / suffix,
        "accuracy_network": output_root / "accuracy_network_monthly" / suffix,
        "ttff_station": output_root / "ttff_monthly" / suffix,
        "ttff_network": output_root / "ttff_network_monthly" / suffix,
    }
    for path, df in (
        (out_paths["accuracy_station"], accuracy_station),
        (out_paths["accuracy_network"], accuracy_network),
        (out_paths["ttff_station"], ttff_station),
        (out_paths["ttff_network"], ttff_network),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)

    result = MonthlyRollupResult(
        period=period_label,
        mode=mode,
        engine_version=engine_version,
        accuracy_station=out_paths["accuracy_station"],
        accuracy_network=out_paths["accuracy_network"],
        ttff_station=out_paths["ttff_station"],
        ttff_network=out_paths["ttff_network"],
        n_dates_pooled=len(found),
    )
    logger.info(
        "monthly rollup: %s mode=%s pooled %d dates; wrote 4 Parquets",
        period_label, mode, len(found),
    )
    if record_provenance:
        _record_provenance(result)
    return result


def _record_provenance(res: MonthlyRollupResult) -> None:
    DEFAULT_PROVENANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "period": res.period,
        "mode": res.mode,
        "engine_version": res.engine_version,
        "n_dates_pooled": res.n_dates_pooled,
        "accuracy_station": str(res.accuracy_station),
        "accuracy_network": str(res.accuracy_network),
        "ttff_station": str(res.ttff_station),
        "ttff_network": str(res.ttff_network),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    with DEFAULT_PROVENANCE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


__all__ = ["MonthlyRollupResult", "compute_monthly"]
