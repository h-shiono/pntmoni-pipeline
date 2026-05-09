"""Unit tests for the CLASLIB processing wrapper.

The actual ``rnx2rtkp`` invocation requires a built binary and aux data
files; that path is exercised only in `integration` tests. These tests
cover the pure-Python pieces: RINEX header parsing, per-station config
substitution, gunzip helper, and path layout.
"""
from __future__ import annotations

import gzip
import textwrap
from datetime import date
from pathlib import Path

from pntmoni_pipeline.processing import _workspace, claslib_engine
from pntmoni_pipeline.processing._config import write_station_config
from pntmoni_pipeline.processing._obs_header import ObsIdentity, read_identity


_RINEX3_HEADER_FIXTURE = (
    "     3.02           OBSERVATION DATA    M (MIXED)           "
    "RINEX VERSION / TYPE\n"
    "BINEX2RINEX  2.12   GSI, JAPAN          20260402 21:07:42UTCPGM / RUN BY / DATE\n"
    "0231                                                        MARKER NAME\n"
    "GEODETIC                                                    MARKER TYPE\n"
    "GSI, JAPAN          GEOSPATIAL INFORMATION AUTHORITY OF JAPAOBSERVER / AGENCY\n"
    "00000               TPS NETG5           5.2.6,08/May/2020   "
    "REC # / TYPE / VERS\n"
    "                    TRM159900.00    GSI4                    ANT # / TYPE\n"
    " -3788392.1483  3263901.8805  3946051.6482                  APPROX POSITION XYZ\n"
    "                                                            END OF HEADER\n"
)


def test_read_identity_plain(tmp_path: Path) -> None:
    obs = tmp_path / "02310910.26o"
    obs.write_text(_RINEX3_HEADER_FIXTURE)
    ident = read_identity(obs)
    # Receiver: cols 20-40 of the line.
    assert ident.receiver == "TPS NETG5           "
    # Antenna: cols 20-40 with cols 16-20 forced to NONE.
    assert ident.antenna.endswith("NONE")
    assert ident.antenna.startswith("TRM159900.00    ")
    assert len(ident.antenna) == 20


def test_read_identity_gzipped(tmp_path: Path) -> None:
    obs = tmp_path / "02310910.26o.gz"
    with gzip.open(obs, "wt") as f:
        f.write(_RINEX3_HEADER_FIXTURE)
    ident = read_identity(obs)
    assert ident.receiver.strip() == "TPS NETG5"
    assert ident.antenna.endswith("NONE")


def test_write_station_config_substitutes_lines(tmp_path: Path) -> None:
    template = tmp_path / "kinematic_p30.conf"
    template.write_text(
        textwrap.dedent(
            """\
            pos1-posmode = ppp-rtk
            pos1-rectype = SOMETHING_OLD
            pos1-elmask  = 15
            ant1-anttype = JAVAD_OLD             RADO
            ant1-postype = single
            """
        )
    )
    identity = ObsIdentity(
        receiver="TPS NETG5           ",
        antenna="TRM159900.00    NONE",
    )
    out = tmp_path / "kinematic_p30_0231.conf"
    digest = write_station_config(template, out, identity)

    rendered = out.read_text()
    assert "pos1-rectype = TPS NETG5" in rendered
    assert "ant1-anttype = TRM159900.00    NONE" in rendered
    # Lines we did not touch are unchanged.
    assert "pos1-posmode = ppp-rtk" in rendered
    assert "pos1-elmask  = 15" in rendered
    assert "ant1-postype = single" in rendered
    assert len(digest) == 64  # SHA-256 hex


def test_write_station_config_hash_changes_with_identity(tmp_path: Path) -> None:
    template = tmp_path / "x.conf"
    template.write_text("pos1-rectype = X\nant1-anttype = Y\n")
    a = write_station_config(
        template, tmp_path / "a.conf",
        ObsIdentity(receiver="REC_A", antenna="ANT_A"),
    )
    b = write_station_config(
        template, tmp_path / "b.conf",
        ObsIdentity(receiver="REC_B", antenna="ANT_B"),
    )
    assert a != b


def test_gunzip_to_idempotent(tmp_path: Path) -> None:
    src = tmp_path / "x.gz"
    payload = b"hello world\n" * 100
    with gzip.open(src, "wb") as f:
        f.write(payload)
    dst = tmp_path / "x"
    _workspace.gunzip_to(src, dst)
    assert dst.read_bytes() == payload
    # Re-running does not error and does not corrupt the dst.
    _workspace.gunzip_to(src, dst)
    assert dst.read_bytes() == payload


def test_path_layout_helpers() -> None:
    raw = Path("data/raw")
    target = date(2026, 4, 1)  # DOY 091
    assert claslib_engine.rinex_obs_path(raw, target, "0231") == (
        Path("data/raw/rinex/2026/091/02310910.26o.gz")
    )
    assert claslib_engine.output_dir(Path("data/processed"), "kinematic_p30", target) == (
        Path("data/processed/kinematic_p30/2026/091")
    )


def test_list_obs_files_finds_acquired(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    target = date(2026, 4, 1)
    doy_dir = raw / "rinex" / "2026" / "091"
    doy_dir.mkdir(parents=True)
    # Two valid obs files plus a nav file (should be ignored).
    for name in ("02310910.26o.gz", "02320910.26o.gz", "02310910.26N.tar.gz"):
        (doy_dir / name).write_bytes(b"")
    found = claslib_engine.list_obs_files(raw, target)
    assert sorted(p.name for p in found) == ["02310910.26o.gz", "02320910.26o.gz"]
