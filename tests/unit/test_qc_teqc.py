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


def test_mask_qzs_lncb_health_clears_lsb_only() -> None:
    # health = 1 (only L1C/B bit set, the dominant case for QZS broadcasting
    # L1C/A) → 0 so teqc treats the SV as healthy.
    assert _nav_rewrite._mask_qzs_lncb_health("1.000000000000e+00") == " 0.000000000000D+00"
    # health = 0 (everything healthy) stays 0.
    assert _nav_rewrite._mask_qzs_lncb_health("0.000000000000e+00") == " 0.000000000000D+00"
    # health = 16 (L1C/A bit set, e.g. QZS-1R broadcasting L1C/B): preserved.
    assert _nav_rewrite._mask_qzs_lncb_health("1.600000000000e+01") == " 1.600000000000D+01"
    # health = 17 (L1C/A bit set + L1C/B bit set) → 16; teqc still excludes.
    assert _nav_rewrite._mask_qzs_lncb_health("1.700000000000e+01") == " 1.600000000000D+01"
    # health = 62 (legacy J01 in 2022, all signals unhealthy except L1C/B): preserved.
    assert _nav_rewrite._mask_qzs_lncb_health("6.200000000000e+01") == " 6.200000000000D+01"
    # health = 63 → 62 (LSB cleared, others preserved).
    assert _nav_rewrite._mask_qzs_lncb_health("6.300000000000e+01") == " 6.200000000000D+01"


def test_rewrite_qnav_to_qzs_masks_l1cb_health_in_bo6(tmp_path: Path) -> None:
    """Broadcast orbit 6 field 2 = SV health; LSB must be cleared."""
    src = tmp_path / "x.qnav"
    # One full ephemeris: epoch + 7 broadcast orbits. BO6 has health=1.
    src.write_text(textwrap.dedent("""\
        2.12              N: GNSS NAV DATA    J: QZSS             RINEX VERSION / TYPE
        convbin             RTKLIB              20260401 12:00:00 PGM / RUN BY / DATE
                                                                    END OF HEADER
        J03 26  4  1  0  0  0.0 1.000000000000e-06 2.000000000000e-13 0.000000000000e+00
             6.100000000000e+01 1.000000000000e+02 3.000000000000e-09 4.000000000000e+00
             5.000000000000e-05 7.000000000000e-02 8.000000000000e-05 6.000000000000e+03
             2.000000000000e+05 9.000000000000e-07 1.000000000000e+00 2.000000000000e-07
             3.000000000000e-01 4.000000000000e+02 5.000000000000e+00 6.000000000000e-09
             7.000000000000e-10 2.000000000000e+00 2.000000000000e+03 0.000000000000e+00
             2.800000000000e+00 1.000000000000e+00 4.000000000000e-10 8.000000000000e+02
             2.000000000000e+05 0.000000000000e+00
    """))
    dst = tmp_path / "x.qzs"
    _nav_rewrite.rewrite_qnav_to_qzs(src, dst)
    out_lines = dst.read_text().splitlines()
    # Find the epoch line (starts with PRN "03"), BO6 is 6 lines below.
    eph_idx = next(i for i, l in enumerate(out_lines) if l.startswith("03 "))
    bo6 = out_lines[eph_idx + 6]
    # SV accuracy (field 1) untouched; SV health (field 2) must be masked to 0.
    assert "2.800000000000D+00" in bo6[3:22], f"SV accuracy mutated: {bo6!r}"
    assert "0.000000000000D+00" in bo6[22:41], f"health not masked: {bo6!r}"


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


# ---------------------------------------------------------------------------
# Summary parser
# ---------------------------------------------------------------------------

from pntmoni_pipeline.qc import _summary, _summary_parser  # noqa: E402


_SYNTHETIC_S26 = """\
                    Quality Check (qc)
4-character ID          : 0231
Receiver type           : TPS NETG5 (# = 00000) (fw = 5.2.6,08/May/2020)
Antenna type            : TRM159900.00    NONE
  antenna WGS 84 (xyz)  : -3788392.1483 3263901.8805 3946051.6482 (m)

Total satellites w/ obs : 50
Epochs w/ observations  :   2880
Possible obs >  10.0 deg:  44000
Complete obs >  10.0 deg:  43000
 Deleted obs >  10.0 deg:     50

Observation interval :   30.000 sec

elev (deg)  tot slps <ION rms, m>        5=%       1|m      15=%       2|m
 85 - 90    500    0   0.000000
 80 - 85   1500    0   0.000000
 75 - 80   3000    0   0.000000
 70 - 75   3000    0   0.000000
 65 - 70   3500    0   0.000000
 60 - 65   3800    0   0.000000
 55 - 60   4000    0   0.000000
 50 - 55   4700    0   0.000000
 45 - 50   4500    0   0.000000
 40 - 45   5500    0   0.000000
 35 - 40   5800    0   0.000000
 30 - 35   6300    0   0.000000
 25 - 30   7000    0   0.000000
 20 - 25   7900    0   0.000000
 15 - 20   8200    1   0.000000
 10 - 15   8400    7   0.000000
  5 - 10   8200   28   0.000000
  0 -  5     50    0   0.000000
    <  0  14000    0   0.000000

 SV  obs>10  # del <elev> MP12 rms [m]  < 25   < 25   < 25   > 25   > 25   > 25
G18    900    0  35.0   0.123
mean MP12 rms        :  0.123 m

elev (deg)  tot slps <MP12 rms, m>        5=%       1|m      15=%       2|m
 85 - 90    300    0   0.180000
 80 - 85    900    0   0.181000
 75 - 80   1900    0   0.182000
 70 - 75   1700    0   0.183000
 65 - 70   1900    0   0.184000
 60 - 65   2100    0   0.185000
 55 - 60   2200    0   0.186000
 50 - 55   2700    0   0.187000
 45 - 50   2500    0   0.188000
 40 - 45   3200    0   0.189000
 35 - 40   3300    0   0.190000
 30 - 35   3500    0   0.191000
 25 - 30   3900    0   0.192000
 20 - 25   4400    0   0.193000
 15 - 20   4600    0   0.194000
 10 - 15   4700    0   0.195000
  5 - 10   4800    0   0.196000
  0 -  5     30    0   0.197000
    <  0   7400    0   0.198000

elev (deg)  tot SN1 sig    mean          2|0       4|0       6|0       8|0
 85 - 90    290   3.082   50.668 ##|||
 80 - 85    910   2.000   50.700 #||
 75 - 80   1900   1.700   50.300 #||
 70 - 75   1700   1.800   49.800 #||
 65 - 70   1900   1.700   49.600 #||
 60 - 65   2100   1.800   49.200 #||
 55 - 60   2200   1.700   48.700 #||
 50 - 55   2600   1.700   48.100 #||
 45 - 50   2500   1.600   47.300 #||
 40 - 45   3100   1.500   46.200 #||
 35 - 40   3200   1.600   45.000 #||
 30 - 35   3500   1.500   43.500 #||
 25 - 30   3900   1.500   42.000 #||
 20 - 25   4400   1.500   40.400 #||
 15 - 20   4600   1.800   38.600 #||
 10 - 15   4700   2.100   36.800 #||
  5 - 10   4700   2.300   34.800 #||
  0 -  5     30   6.500   32.300 #||
    <  0   7400   5.300   41.400 #||
"""


def test_parse_teqc_summary_extracts_header_fields(tmp_path: Path) -> None:
    p = tmp_path / "x.26S"
    p.write_text(_SYNTHETIC_S26)
    s = _summary_parser.parse_teqc_summary(p)
    assert s.id == "0231"
    assert s.rec_type == "TPS NETG5"
    assert s.rec_num == "00000"
    assert s.rec_fw_ver == "5.2.6,08/May/2020"
    assert s.ant_type == "TRM159900.00    NONE"
    assert s.approx_pos_x == pytest.approx(-3788392.1483)
    assert s.approx_pos_y == pytest.approx(3263901.8805)
    assert s.approx_pos_z == pytest.approx(3946051.6482)
    assert s.epochs_w_obs == 2880
    assert s.visibility == pytest.approx(43000 / 44000)


def test_parse_teqc_summary_extracts_ion_mp_sn_blocks(tmp_path: Path) -> None:
    p = tmp_path / "x.26S"
    p.write_text(_SYNTHETIC_S26)
    s = _summary_parser.parse_teqc_summary(p)
    assert len(s.ion) == 19
    assert s.ion["85 - 90"] == (500.0, 0.0, 0.0)
    assert s.ion["10 - 15"] == (8400.0, 7.0, 0.0)
    assert "MP12" in s.mp
    assert len(s.mp["MP12"]) == 19
    assert s.mp["MP12"]["85 - 90"][2] == pytest.approx(0.180)
    assert "SN1" in s.sn
    assert len(s.sn["SN1"]) == 19
    assert s.sn["SN1"]["85 - 90"][1] == pytest.approx(3.082)


def test_to_wide_row_matches_legacy_column_order(tmp_path: Path) -> None:
    p = tmp_path / "x.26S"
    p.write_text(_SYNTHETIC_S26)
    s = _summary_parser.parse_teqc_summary(p)
    row = _summary_parser.to_wide_row(s)
    cols = _summary_parser.wide_columns()
    assert set(row.keys()) == set(cols)
    # ION block: 19 elev × 3 axes = 57 cols.
    assert "ION_85_-_90_tot" in cols
    assert "ION____<__0_rms" in cols
    assert row["ION_85_-_90_tot"] == 500.0
    # MP block: 6 freqs × 19 elev × 3 axes = 342 cols. MP21 absent in
    # the synthetic file → its values stay NaN.
    import math
    assert math.isnan(row["MP21_85_-_90_tot"])
    assert row["MP12_85_-_90_rms"] == pytest.approx(0.180)
    # SN block: 4 freqs × 19 elev × 3 axes = 228 cols.
    assert row["SN1_85_-_90_sig"] == pytest.approx(3.082)


def test_summarize_doy_writes_parquet(tmp_path: Path) -> None:
    target = date(2026, 4, 1)
    in_root = tmp_path / "qc_teqc"
    doy_dir = in_root / "2026" / "091"
    doy_dir.mkdir(parents=True)
    for station in ("0231", "0232"):
        (doy_dir / f"{station}0910.26S").write_text(_SYNTHETIC_S26)
    out_root = tmp_path / "qc_summary"
    res = _summary.summarize_doy(
        target,
        input_root=in_root, output_root=out_root,
        record_provenance=False,
    )
    assert res.n_stations == 2
    assert res.parquet_path.is_file()
    import pandas as pd
    df = pd.read_parquet(res.parquet_path)
    assert len(df) == 2
    # Both stations have the synthetic id "0231" since the parser reads
    # the inline 4-character ID, not the filename.
    assert (df["id"] == "0231").all()
    # Provenance columns appear at the end of the schema.
    assert "date" in df.columns
    assert df["date"].iloc[0] == "2026-04-01"
    # Wide schema preserved.
    assert "MP12_85_-_90_rms" in df.columns
