"""Tests for the L5copy ATX patcher."""
from __future__ import annotations

from pathlib import Path

from pntmoni_pipeline.processing._aux_data import build_l5copy


_HEADER = (
    "     1.4            M                                       ANTEX VERSION / SYST\n"
    "A                                                           PCV TYPE / REFANT   \n"
)


def _antenna_block(*, code: str, ant_name: str, freqs: list[str]) -> str:
    lines = [
        "                                                            START OF ANTENNA    \n",
        f"{ant_name.ljust(60)}TYPE / SERIAL NO    \n",
        "                                             0    29-JAN-17 METH / BY / # / DATE\n",
        "     0.0                                                    DAZI                \n",
        "     0.0  17.0   1.0                                        ZEN1 / ZEN2 / DZEN  \n",
        f"     {len(freqs)}                                                      # OF FREQUENCIES    \n",
        "  2020     1     1     0     0    0.0000000                 VALID FROM          \n",
        "TESTING_SINEX                                               SINEX CODE          \n",
    ]
    for fc in freqs:
        lines.append(f"   {fc}                                                      START OF FREQUENCY  \n")
        lines.append("    100.00      0.00   2000.00                              NORTH / EAST / UP   \n")
        lines.append(f"   NOAZI {fc}_PCV_VALUES_PCV_VALUES_PCV_VALUES_PCV_VALUES\n")
        lines.append(f"   {fc}                                                      END OF FREQUENCY    \n")
    lines.append("                                                            END OF ANTENNA      \n")
    return "".join(lines)


def test_l5copy_inserts_g05_when_g02_present_g05_absent(tmp_path: Path) -> None:
    block = _antenna_block(code="G", ant_name="GPS_ANT_TEST", freqs=["G01", "G02"])
    src = tmp_path / "src.atx"
    src.write_text(_HEADER + block, encoding="utf-8")
    dst = tmp_path / "dst.atx"

    summary = build_l5copy(src, dst, source_sha256="abc" * 16)

    out = dst.read_text(encoding="utf-8")
    assert "G05                                                      START OF FREQUENCY" in out
    assert "G05                                                      END OF FREQUENCY" in out
    # The copied G05 sub-block keeps G02's NOAZI line verbatim (only the
    # START/END frequency code markers are retargeted).
    g05_start = out.index("G05                                                      START OF FREQUENCY")
    g05_end = out.index("G05                                                      END OF FREQUENCY")
    g05_body = out[g05_start:g05_end]
    assert "NOAZI G02_PCV_VALUES" in g05_body
    assert summary.n_g05_inserted == 1
    assert summary.n_j05_inserted == 0
    assert summary.n_antennas_seen == 1


def test_l5copy_inserts_j05_when_j02_present_j05_absent(tmp_path: Path) -> None:
    block = _antenna_block(code="J", ant_name="QZS_ANT_TEST", freqs=["J01", "J02"])
    src = tmp_path / "src.atx"
    src.write_text(_HEADER + block, encoding="utf-8")
    dst = tmp_path / "dst.atx"

    summary = build_l5copy(src, dst, source_sha256="def" * 16)

    out = dst.read_text(encoding="utf-8")
    assert "J05                                                      START OF FREQUENCY" in out
    assert summary.n_j05_inserted == 1


def test_l5copy_noop_when_g05_already_present(tmp_path: Path) -> None:
    block = _antenna_block(code="G", ant_name="GPS_ANT_FULL", freqs=["G01", "G02", "G05"])
    src = tmp_path / "src.atx"
    src.write_text(_HEADER + block, encoding="utf-8")
    dst = tmp_path / "dst.atx"

    summary = build_l5copy(src, dst, source_sha256="0" * 64)

    out = dst.read_text(encoding="utf-8")
    # exactly one G05 block (no duplication)
    assert out.count("G05                                                      START OF FREQUENCY") == 1
    assert summary.n_g05_inserted == 0


def test_l5copy_noop_when_no_l2_no_l5(tmp_path: Path) -> None:
    block = _antenna_block(code="G", ant_name="GPS_L1_ONLY", freqs=["G01"])
    src = tmp_path / "src.atx"
    src.write_text(_HEADER + block, encoding="utf-8")
    dst = tmp_path / "dst.atx"

    summary = build_l5copy(src, dst, source_sha256="0" * 64)

    out = dst.read_text(encoding="utf-8")
    # No G05 frequency block inserted (the provenance header references
    # the count "G05 inserts: 0" which incidentally contains 'G05', so
    # check for the actual frequency marker instead).
    assert "G05                                                      START OF FREQUENCY" not in out
    assert summary.n_g05_inserted == 0


def test_l5copy_updates_num_frequencies(tmp_path: Path) -> None:
    block = _antenna_block(code="G", ant_name="GPS_BUMP", freqs=["G01", "G02"])
    src = tmp_path / "src.atx"
    src.write_text(_HEADER + block, encoding="utf-8")
    dst = tmp_path / "dst.atx"
    build_l5copy(src, dst, source_sha256="0" * 64)

    out = dst.read_text(encoding="utf-8")
    # The count should be bumped 2 → 3.
    assert "     3                                                      # OF FREQUENCIES" in out
    assert "     2                                                      # OF FREQUENCIES" not in out


def test_l5copy_provenance_header_present(tmp_path: Path) -> None:
    block = _antenna_block(code="G", ant_name="GPS_PROV", freqs=["G01", "G02"])
    src = tmp_path / "src.atx"
    src.write_text(_HEADER + block, encoding="utf-8")
    dst = tmp_path / "dst.atx"
    build_l5copy(src, dst, source_sha256="abcdef0123456789" * 4)
    out = dst.read_text(encoding="utf-8")
    assert "PNTMONI L5COPY DERIVATION" in out
    assert "source-sha256: abcdef0123456789" in out
    assert "algorithm-version: 1" in out
