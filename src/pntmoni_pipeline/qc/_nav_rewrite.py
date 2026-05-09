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
    """Rewrite a convbin QNAV file as a teqc-compatible QZSS NAV file."""
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
            else:
                fout.write(
                    "   "
                    f"{_str2rnx_d(line[5:23])}"
                    f"{_str2rnx_d(line[24:42])}"
                    f"{_str2rnx_d(line[43:61])}"
                    f"{_str2rnx_d(line[62:80])}\n"
                )


__all__ = [
    "GAL_HEADER",
    "QZS_HEADER",
    "rewrite_lnav_to_gal",
    "rewrite_qnav_to_qzs",
]
