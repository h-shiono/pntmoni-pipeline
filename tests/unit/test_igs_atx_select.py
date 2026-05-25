"""Tests for the date-based ATX selection guard (methodology §2.1)."""
from __future__ import annotations

from datetime import date

import pytest

from pntmoni_pipeline.acquisition.igs_atx import IGS20_START, select_atx_for_date


def test_on_switch_date_returns_igs20():
    assert select_atx_for_date(IGS20_START) == "igs20.atx"


def test_after_switch_returns_igs20():
    assert select_atx_for_date(date(2025, 4, 1)) == "igs20.atx"


def test_before_switch_raises():
    with pytest.raises(NotImplementedError, match="igs14"):
        select_atx_for_date(date(2022, 11, 26))


def test_well_before_switch_raises():
    with pytest.raises(NotImplementedError):
        select_atx_for_date(date(2021, 1, 1))
