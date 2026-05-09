"""Unit tests for TTFF extraction (analysis/_ttff.py)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pntmoni_pipeline.analysis._ttff import (
    NMEA_Q_FIX,
    NMEA_Q_FLOAT,
    detect_reset_period_from_config,
    extract_events,
    parse_pos_epochs,
    parse_pos_quality,
    record,
    summarize,
)


def test_extract_events_first_window_cold_start() -> None:
    # 30s ti × 30 epochs = 900s window; resets at start of each window.
    # Window 0: Q sequence converges 1,1,5,4,...
    qs = [1, 1, 5, NMEA_Q_FIX, NMEA_Q_FIX] + [NMEA_Q_FIX] * 25
    events = list(extract_events(qs, reset_period_sec=900, sampling_interval_sec=30))
    assert len(events) == 1
    e = events[0]
    assert e.window_idx == 0
    assert e.reset_epoch_idx == 0
    assert e.fixed_epoch_idx == 3
    assert e.n_epochs_to_fix == 3
    assert e.ttff_sec == 90.0


def test_extract_events_unfixed_window_yields_none() -> None:
    qs = [1] * 30                  # never reaches Q=4
    events = list(extract_events(qs, reset_period_sec=900, sampling_interval_sec=30))
    assert len(events) == 1
    assert events[0].fixed is False
    assert events[0].ttff_sec is None


def test_extract_events_partial_last_window() -> None:
    # 1.5 windows of data → 2 events (second window short, fixed early)
    qs = [NMEA_Q_FIX] * 30 + [NMEA_Q_FLOAT, NMEA_Q_FIX, NMEA_Q_FIX, NMEA_Q_FIX, NMEA_Q_FIX]
    events = list(extract_events(qs, reset_period_sec=900, sampling_interval_sec=30))
    assert len(events) == 2
    assert events[0].ttff_sec == 0.0          # first epoch already fixed
    assert events[1].ttff_sec == 30.0         # one epoch to fix in window 1


def test_extract_events_validates_arguments() -> None:
    with pytest.raises(ValueError):
        list(extract_events([1, 4], reset_period_sec=900, sampling_interval_sec=0))
    with pytest.raises(ValueError):
        # 900 not divisible by 7
        list(extract_events([1, 4], reset_period_sec=900, sampling_interval_sec=7))


def test_summarize_fix_rate_and_percentiles() -> None:
    qs = (
        [1, 1, 5, NMEA_Q_FIX] + [NMEA_Q_FIX] * 26 +    # window 0: ttff=90s
        [1, 5, 5, 5, NMEA_Q_FIX] + [NMEA_Q_FIX] * 25 + # window 1: ttff=120s
        [1] * 30                                       # window 2: unfixed
    )
    events = list(extract_events(qs, reset_period_sec=900, sampling_interval_sec=30))
    s = summarize(
        events,
        station="0231", date="2026-04-01", mode="ttff_test",
        reset_period_sec=900, sampling_interval_sec=30,
    )
    assert s.n_windows == 3
    assert s.n_fixed == 2
    assert s.n_unfixed == 1
    assert s.fix_success_rate == pytest.approx(2 / 3)
    assert s.ttff_min_sec == 90.0
    assert s.ttff_max_sec == 120.0
    # Median of [90, 120] is 105
    assert s.ttff_p50_sec == pytest.approx(105.0)


def test_parse_pos_quality_skips_non_gpgga(tmp_path: Path) -> None:
    pos = tmp_path / "x.pos"
    pos.write_text(
        "$GPRMC,000000.00,A,3827.92,N,13915.20,E,0.00,0.00,010426,,,*42\n"
        "$GPGGA,000000.00,3827.92,N,13915.20,E,4,12,1.0,9.0,M,38.2,M,0.0,*43\n"
        "# comment line\n"
        "$GPGGA,000030.00,3827.92,N,13915.20,E,5,11,1.1,9.1,M,38.2,M,0.0,*44\n"
        "$GPGGA,000100.00,3827.92,N,13915.20,E,1,8,2.0,9.5,M,38.2,M,0.0,*45\n"
    )
    qs = parse_pos_quality(pos)
    assert qs == [4, 5, 1]


def test_detect_reset_period_from_config(tmp_path: Path) -> None:
    conf = tmp_path / "x.conf"
    conf.write_text(
        "pos1-elmask = 15\n"
        "misc-floatcnt = 0\n"
        "misc-regularly = 900   # 15 minutes\n"
        "ant1-postype  = single\n"
    )
    assert detect_reset_period_from_config(conf) == 900


def test_detect_reset_period_returns_none_when_absent(tmp_path: Path) -> None:
    conf = tmp_path / "x.conf"
    conf.write_text("pos1-elmask = 15\nmisc-floatcnt = 0\n")
    assert detect_reset_period_from_config(conf) is None


def test_extract_events_dict_with_gap_does_not_drift(tmp_path: Path) -> None:
    # Sparse epoch map: epochs 60..89 are missing entirely (a gap).
    # The 1st window converges; the 2nd window has a fix at epoch 35;
    # the 3rd window (60..89) has no observations → unfixed; the 4th
    # window (90..119) has an early fix.
    epochs = {}
    # Window 0: epochs 0..29, fix at epoch 4.
    for i in range(30):
        epochs[i] = NMEA_Q_FLOAT if i < 4 else NMEA_Q_FIX
    # Window 1: epochs 30..59, fix at epoch 35.
    for i in range(30, 60):
        epochs[i] = 1 if i == 30 else (NMEA_Q_FLOAT if i < 35 else NMEA_Q_FIX)
    # Window 2: NO epochs (gap).
    # Window 3: epochs 90..119, fix at epoch 91 (after a single Q=5 epoch).
    epochs[90] = NMEA_Q_FLOAT
    for i in range(91, 120):
        epochs[i] = NMEA_Q_FIX

    events = list(extract_events(
        epochs, reset_period_sec=900, sampling_interval_sec=30, n_windows=4,
    ))
    assert len(events) == 4
    assert events[0].ttff_sec == 120.0   # 4 epochs × 30s
    assert events[1].ttff_sec == 150.0   # 5 epochs × 30s
    assert events[2].ttff_sec is None    # no observations in window
    assert events[3].ttff_sec == 30.0    # 1 epoch × 30s


def test_parse_pos_epochs_aligns_to_gpst_day(tmp_path: Path) -> None:
    # NMEA UTC 23:59:42 → GPST 00:00:00 (epoch 0 of GPST day 2026-04-01).
    # NMEA UTC 00:00:12 → GPST 00:00:30 (epoch 1).
    pos = tmp_path / "x.pos"
    pos.write_text(
        "$GPGGA,235942.00,3827.92,N,13915.20,E,4,12,1.0,9.0,M,38.2,M,0.0,*40\n"
        "$GPGGA,000012.00,3827.92,N,13915.20,E,1,12,1.0,9.0,M,38.2,M,0.0,*41\n"
        "$GPGGA,000042.00,3827.92,N,13915.20,E,5,12,1.0,9.0,M,38.2,M,0.0,*42\n"
    )
    epochs = parse_pos_epochs(pos)
    assert epochs == {0: 4, 1: 1, 2: 5}


def test_parse_pos_epochs_handles_observation_gap(tmp_path: Path) -> None:
    # GPST 00:00:00 (epoch 0), then jump to GPST 00:01:30 (epoch 3).
    # Epochs 1, 2 missing → only 0 and 3 present in dict.
    pos = tmp_path / "x.pos"
    pos.write_text(
        "$GPGGA,235942.00,3827.92,N,13915.20,E,4,12,1.0,9.0,M,38.2,M,0.0,*40\n"
        "$GPGGA,000112.00,3827.92,N,13915.20,E,4,12,1.0,9.0,M,38.2,M,0.0,*41\n"
    )
    epochs = parse_pos_epochs(pos)
    assert epochs == {0: 4, 3: 4}


def test_record_jsonl_append(tmp_path: Path) -> None:
    qs = [1, 5, NMEA_Q_FIX] + [NMEA_Q_FIX] * 27
    events = list(extract_events(qs, reset_period_sec=900, sampling_interval_sec=30))
    s = summarize(
        events,
        station="0231", date="2026-04-01", mode="m",
        reset_period_sec=900, sampling_interval_sec=30,
    )
    log = tmp_path / "ttff.jsonl"
    record(s, path=log)
    record(s, path=log)
    lines = log.read_text().strip().splitlines()
    assert len(lines) == 2
    e = json.loads(lines[0])
    assert e["station"] == "0231"
    assert e["reset_period_sec"] == 900
    assert e["n_fixed"] == 1
    assert e["fix_success_rate"] == 1.0
