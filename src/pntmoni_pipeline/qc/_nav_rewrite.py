"""Galileo / QZSS NAV header rewrite for teqc compatibility.

teqc 2019Feb25 cannot read RINEX 3+ files; ``convbin`` (RTKLIB) is
used to drop down to RINEX 2.x. The Galileo and QZSS NAV files
``convbin`` produces (``.lnav``, ``.qnav``) carry RINEX-2.x format
data lines but a header label that teqc does not recognise. The
classic workaround (from gnss_research_toolbox/eval_geonet.py) is to
rewrite the header to a teqc-accepted form (``E: Galileo NAV DATA``,
``J: QZSS NAV DATA``) and reformat data lines to use the ``D``
exponent style teqc expects.

Pure-Python (no third-party dependency); identical I/O semantics to
the legacy ``conv_lnav`` / ``conv_qnav`` functions.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

GAL_HEADER = (
    "     2.12           E: Galileo NAV DATA"
    "                     RINEX VERSION / TYPE"
)
QZS_HEADER = (
    "     2.13           J: QZSS NAV DATA"
    "                        RINEX VERSION / TYPE"
)

_PASSTHROUGH_HEADER_LABELS = (
    "PGM / RUN BY / DATE",
    "COMMENT",
    "END OF HEADER",
)


def _str2rnx_d(s: str) -> str:
    """Convert a ``e``-format float string to RINEX-2 ``D`` form.

    Returns 14 spaces if ``s`` is not a valid float (legacy behaviour).
    """
    try:
        v = "{:+14.12e}".format(float(s)).replace("e", "D")
    except ValueError:
        return " " * 14
    return (" " + v[1:]) if v[0] == "+" else v


def _mask_qzs_lncb_health(s: str) -> str:
    """Clear the L1C/B health bit (LSB) from a QZSS LNAV SV-health field.

    Per IS-QZSS-PNT-006 §4.1.2.3(4) the 6-bit SV-health word is:
        bit 5 (MSB)  L1 Health     (L1C/A or L1C/B, whichever transmitted)
        bit 4        L1C/A Health
        bit 3        L2 Health
        bit 2        L5 Health
        bit 1        L1C Health
        bit 0 (LSB)  L1C/B Health
    L1C/A and L1C/B are exclusively transmitted, so the bit corresponding
    to the *not-currently-transmitted* signal is set to 1 by design.
    QZSS satellites broadcasting L1C/A (the majority) therefore set
    health=1 — which teqc, written before this convention, treats as
    "SV unhealthy" and excludes from QC. Clearing only the LSB recovers
    those SVs while leaving QZS-1R (which broadcasts L1C/B and so has
    L1C/A bit set, value ≥16) correctly marked unhealthy for L1C/A QC.
    """
    try:
        h = int(float(s))
    except ValueError:
        return _str2rnx_d(s)
    return _str2rnx_d(f"{h & ~0b00001:d}")


def _is_passthrough_header(line: str) -> bool:
    return any(label in line for label in _PASSTHROUGH_HEADER_LABELS)


def rewrite_lnav_to_gal(lnav_path: Path, out_path: Path) -> None:
    """Rewrite a convbin LNAV file as a teqc-compatible Galileo NAV file."""
    with lnav_path.open("r") as fin, out_path.open("w") as fout:
        for line in fin:
            if "RINEX VERSION / TYPE" in line:
                fout.write(GAL_HEADER + "\n")
            elif _is_passthrough_header(line):
                fout.write(line)
            elif line and line[0] == "E":
                svid = line[1:3]
                t = datetime(
                    int(line[4:8]), int(line[9:11]), int(line[12:14]),
                    int(line[15:17]), int(line[18:20]), int(line[21:23]),
                    tzinfo=UTC,
                ).strftime("%y %m %d %H %M %S").replace(" 0", "  ")
                fout.write(
                    f"{svid:>2} {t}.0"
                    f"{_str2rnx_d(line[24:42])}"
                    f"{_str2rnx_d(line[43:61])}"
                    f"{_str2rnx_d(line[62:80])}\n"
                )
            else:
                fout.write(
                    "   "
                    f"{_str2rnx_d(line[5:23])}"
                    f"{_str2rnx_d(line[24:42])}"
                    f"{_str2rnx_d(line[43:61])}"
                    f"{_str2rnx_d(line[62:80])}\n"
                )


def rewrite_qnav_to_qzs(qnav_path: Path, out_path: Path) -> None:
    """Rewrite a convbin QNAV file as a teqc-compatible QZSS NAV file.

    Broadcast orbit 6 carries the SV-health word; the L1C/B bit is
    masked there per :func:`_mask_qzs_lncb_health`.
    """
    bo_idx = -1   # -1 = not yet inside an ephemeris; 0..6 = data line of current eph.
    with qnav_path.open("r") as fin, out_path.open("w") as fout:
        for line in fin:
            if "RINEX VERSION / TYPE" in line:
                fout.write(QZS_HEADER + "\n")
            elif _is_passthrough_header(line):
                fout.write(line)
            elif line and line[0] == "J":
                svid = line[1:3]
                t = line[4:23]
                fout.write(
                    f"{svid:>2} {t}"
                    f"{_str2rnx_d(line[24:42])}"
                    f"{_str2rnx_d(line[43:61])}"
                    f"{_str2rnx_d(line[62:80])}\n"
                )
                bo_idx = 0
            else:
                # broadcast orbit 6 (the 6th data line, 0-indexed = 5) carries
                # SV health as field 2 (cols 24..42 of the convbin .qnav)
                if bo_idx == 5:
                    health = _mask_qzs_lncb_health(line[24:42])
                else:
                    health = _str2rnx_d(line[24:42])
                fout.write(
                    "   "
                    f"{_str2rnx_d(line[5:23])}"
                    f"{health}"
                    f"{_str2rnx_d(line[43:61])}"
                    f"{_str2rnx_d(line[62:80])}\n"
                )
                bo_idx = bo_idx + 1 if bo_idx >= 0 else bo_idx


__all__ = [
    "GAL_HEADER",
    "QZS_HEADER",
    "rewrite_lnav_to_gal",
    "rewrite_qnav_to_qzs",
]
