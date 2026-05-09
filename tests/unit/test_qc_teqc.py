"""Unit tests for the QC nav-rewrite + path layout helpers."""
from __future__ import annotations

import textwrap
from datetime import date
from pathlib import Path

import pytest

from pntmoni_pipeline.qc import _nav_rewrite, _teqc


# ---------------------------------------------------------------------------
# Nav header rewrite
# ---------------------------------------------------------------------------

def test_str2rnx_d_format() -> None:
    assert _nav_rewrite._str2rnx_d("1.5e-3") == " 1.500000000000D-03"
    assert _nav_rewrite._str2rnx_d("-2.5e+5") == "-2.500000000000D+05"
    # Invalid → 14 spaces (legacy semantics).
    assert _nav_rewrite._str2rnx_d("not-a-number") == " " * 14
    assert _nav_rewrite._str2rnx_d("") == " " * 14


def test_rewrite_lnav_to_gal_replaces_header_and_data(tmp_path: Path) -> None:
    src = tmp_path / "x.lnav"
    src.write_text(textwrap.dedent("""\
        2.12              N: GNSS NAV DATA    E: Galileo          RINEX VERSION / TYPE
        convbin             RTKLIB              20260401 12:00:00 PGM / RUN BY / DATE
                                                                    END OF HEADER
        E01 2026 04 01 00 00 00 1.234567890123e-04 5.678901234567e-12 1.000000000000e+00
             1.000000000000e+00  2.000000000000e+00  3.000000000000e+00  4.000000000000e+00
    """))
    dst = tmp_path / "x.gal"
    _nav_rewrite.rewrite_lnav_to_gal(src, dst)
    out = dst.read_text()
    # Header rewritten to teqc-recognised "E: Galileo NAV DATA" form.
    assert "E: Galileo NAV DATA" in out
    # Pass-through header labels preserved.
    assert "PGM / RUN BY / DATE" in out
    assert "END OF HEADER" in out
    # Per-sat data line: svid 2-char + reformatted yy/m/d epoch.
    assert "01 26  4  1  0  0  0.0" in out
    # Exponent style converted from "e" to "D".
    assert "1.234567890123D-04" in out
    assert "5.678901234567D-12" in out


def test_rewrite_qnav_to_qzs_replaces_header(tmp_path: Path) -> None:
    # QNAV body line is fixed-width: PRN at cols 0-2, epoch at 3-22, three
    # 19-char floats from col 23 onward. Use the exact column layout
    # convbin emits.
    src = tmp_path / "x.qnav"
    # RINEX 2 NAV body line is 80-column with explicit field widths:
    #   cols 0-2  PRN (3 chars, "J01")
    #   col  3    space
    #   cols 4-22 epoch (19 chars: "yy mm dd hh mm ss.s")
    #   col  23   space
    #   cols 24-41 val1 (18 chars), col 42 space, …
    body_line = (
        "J01"
        " "
        "26  4  1  0  0  0.0"        # 19 chars
        " "
        "1.234567890123e-04"          # 18 chars
        " "
        "5.678901234567e-12"
        " "
        "1.000000000000e+00"
        "\n"
    )
    src.write_text(textwrap.dedent("""\
        2.12              N: GNSS NAV DATA    J: QZSS             RINEX VERSION / TYPE
        convbin             RTKLIB              20260401 12:00:00 PGM / RUN BY / DATE
                                                                    END OF HEADER
    """) + body_line)
    dst = tmp_path / "x.qzs"
    _nav_rewrite.rewrite_qnav_to_qzs(src, dst)
    out = dst.read_text()
    assert "J: QZSS NAV DATA" in out
    assert "PGM / RUN BY / DATE" in out
    # PRN preserved as 2-char svid, original epoch substring preserved.
    assert "01 26  4  1  0  0  0" in out
    # Exponent style converted from "e" to "D".
    assert "1.234567890123D-04" in out
    assert "5.678901234567D-12" in out


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def test_station_id_from_obs_extracts_4_char_prefix() -> None:
    p = Path("data/raw/rinex/2026/091/02310910.26o.gz")
    assert _teqc.station_id_from_obs(p) == "0231"


def test_expected_summary_path_layout() -> None:
    target = date(2026, 4, 1)
    p = _teqc.expected_summary_path(Path("data/processed/qc_teqc"), target, "0231")
    assert p == Path("data/processed/qc_teqc/2026/091/02310910.26S")


def test_list_obs_files_filters_by_extension(tmp_path: Path) -> None:
    target = date(2026, 4, 1)
    doy_dir = _teqc.doy_dir(tmp_path, target)
    doy_dir.mkdir(parents=True)
    # Two valid obs files plus a nav archive (should be skipped).
    for name in ("02310910.26o.gz", "02320910.26o.gz", "02310910.26N.tar.gz"):
        (doy_dir / name).write_bytes(b"")
    found = _teqc.list_obs_files(tmp_path, target)
    assert sorted(p.name for p in found) == ["02310910.26o.gz", "02320910.26o.gz"]


def test_process_doy_raises_when_binaries_missing(tmp_path: Path) -> None:
    target = date(2026, 4, 1)
    with pytest.raises(FileNotFoundError, match="teqc binary"):
        _teqc.process_doy(
            target,
            raw_root=tmp_path,
            output_root=tmp_path / "out",
            teqc=tmp_path / "no-such-teqc",
            convbin=tmp_path / "no-such-convbin",
        )
