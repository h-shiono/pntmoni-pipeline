"""Generate an L5-copy variant of an ANTEX (igs20.atx) file.

PNT Moni's CLAS configuration runs ``pos1-frequency = l1+l2+l5``, which
requires receiver/satellite antenna PCV tables for L5. Upstream
``igs20.atx`` documents L1+L2 PCV for many antennas but omits L5 — the
``igs14_L5copy.atx`` ships by CLASLIB demonstrates the workaround:
inject an L5 frequency block whose PCV values are copied from L2.

This module implements the same patch deterministically against a
fetched ``igs20.atx`` so the derived file is reproducible from the
source SHA-256 + algorithm version.

Scope (per project decision 2026-05-12)
---------------------------------------
- All antenna blocks (satellite + user) are eligible.
- GPS: if ``G02`` exists and ``G05`` does not, copy G02 → G05.
- QZSS: if ``J02`` exists and ``J05`` does not, copy J02 → J05.
- Other constellations (Galileo E*, GLONASS R*, BeiDou C*) are not
  patched here — Galileo E05 (E5a) is generally already present in
  upstream igs20.atx, and the CLAS L1+L2+L5 mode is GPS/QZSS centric.

Provenance
----------
The output file's header gets PNT Moni COMMENT lines documenting:
  - source SHA-256 (igs20.atx fetched)
  - algorithm version (this module's ``ALGORITHM_VERSION``)
  - number of G05 / J05 inserts
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

ALGORITHM_VERSION = "1"

# ANTEX columns 60..80 contain the label; we match by label so the
# parse stays robust to minor whitespace variation in the content.
_LABEL = lambda s: s.ljust(80)[60:].strip()  # noqa: E731

_RE_START_ANTENNA = re.compile(r"^\s*$.{0,60}START OF ANTENNA")  # placeholder
_RE_START_FREQ = re.compile(r"START OF FREQUENCY")
_RE_END_FREQ = re.compile(r"END OF FREQUENCY")
_RE_FREQ_CODE = re.compile(r"^\s+([GREJCRS]\d{2})\s+START OF FREQUENCY")
_RE_NUM_FREQ = re.compile(r"^(\s*)(\d+)(\s+# OF FREQUENCIES)", re.MULTILINE)


@dataclass
class PatchSummary:
    n_antennas_seen: int = 0
    n_g05_inserted: int = 0
    n_j05_inserted: int = 0
    patched_codes: dict[str, int] = field(default_factory=dict)


def _split_blocks(text: str) -> list[str]:
    """Split file content into [pre, block_0, block_1, ..., post] chunks.

    Even indices are non-antenna text (header comments, inter-block
    whitespace, trailer). Odd indices are antenna blocks bounded
    inclusive by their START OF ANTENNA / END OF ANTENNA lines.
    """
    parts: list[str] = []
    pos = 0
    # Find each antenna block by its label markers (column 60+).
    while True:
        start = text.find("START OF ANTENNA", pos)
        if start < 0:
            parts.append(text[pos:])
            break
        # Walk back to the start of that line.
        line_start = text.rfind("\n", 0, start) + 1
        end = text.find("END OF ANTENNA", line_start)
        if end < 0:
            raise ValueError("unterminated START OF ANTENNA block")
        line_end = text.find("\n", end)
        if line_end < 0:
            line_end = len(text)
        line_end += 1  # include the newline
        parts.append(text[pos:line_start])
        parts.append(text[line_start:line_end])
        pos = line_end
    return parts


def _extract_freq_block(block: str, code: str) -> str | None:
    """Return the full text of the ``code`` frequency sub-block, or None."""
    needle = f"   {code}                                                      START OF FREQUENCY"
    start = block.find(needle)
    if start < 0:
        return None
    line_start = block.rfind("\n", 0, start) + 1
    end_marker = f"   {code}                                                      END OF FREQUENCY"
    end = block.find(end_marker, start)
    if end < 0:
        raise ValueError(f"unterminated {code} frequency block")
    line_end = block.find("\n", end)
    if line_end < 0:
        line_end = len(block)
    line_end += 1
    return block[line_start:line_end]


def _has_freq(block: str, code: str) -> bool:
    return _extract_freq_block(block, code) is not None


def _retarget_freq_block(freq_block: str, src_code: str, dst_code: str) -> str:
    """Rewrite ``src_code`` to ``dst_code`` inside a frequency sub-block.

    Only replaces the code in the START/END frequency markers (columns
    0..3 of those lines) — the NORTH/EAST/UP and NOAZI rows are
    code-independent and copied verbatim.
    """
    out: list[str] = []
    for line in freq_block.splitlines(keepends=True):
        if "START OF FREQUENCY" in line or "END OF FREQUENCY" in line:
            out.append(line.replace(src_code, dst_code, 1))
        else:
            out.append(line)
    return "".join(out)


def _update_num_frequencies(block: str, delta: int) -> str:
    """Increment the ``# OF FREQUENCIES`` count by ``delta``.

    Preserves the original column layout — the count sits in a
    right-aligned field of fixed width, so we keep the leading
    whitespace width by adjusting it to compensate for the change in
    digit count.
    """
    if delta == 0:
        return block

    def _bump(match: re.Match[str]) -> str:
        indent, old, suffix = match.group(1), match.group(2), match.group(3)
        new = str(int(old) + delta)
        width = len(indent) + len(old)
        # Right-align new within the same total width so columns 0..k stay fixed.
        new_indent = " " * max(width - len(new), 0)
        return f"{new_indent}{new}{suffix}"

    return _RE_NUM_FREQ.sub(_bump, block, count=1)


def _patch_block(block: str, summary: PatchSummary) -> str:
    """Insert G05/J05 frequency blocks where missing, copied from L2."""
    summary.n_antennas_seen += 1
    delta = 0
    out = block

    # Locate "END OF ANTENNA" line for insertion point.
    end_anchor = "                                                            END OF ANTENNA"
    insert_at = out.rfind(end_anchor)
    if insert_at < 0:
        # Fall back: just find "END OF ANTENNA" substring.
        insert_at = out.rfind("END OF ANTENNA")
        if insert_at < 0:
            raise ValueError("missing END OF ANTENNA in block")
        insert_at = out.rfind("\n", 0, insert_at) + 1
    else:
        insert_at = out.rfind("\n", 0, insert_at) + 1

    inserts: list[str] = []

    # GPS L2 → L5
    g02 = _extract_freq_block(out, "G02")
    if g02 is not None and not _has_freq(out, "G05"):
        inserts.append(_retarget_freq_block(g02, "G02", "G05"))
        summary.n_g05_inserted += 1
        summary.patched_codes["G05"] = summary.patched_codes.get("G05", 0) + 1
        delta += 1

    # QZSS L2 → L5
    j02 = _extract_freq_block(out, "J02")
    if j02 is not None and not _has_freq(out, "J05"):
        inserts.append(_retarget_freq_block(j02, "J02", "J05"))
        summary.n_j05_inserted += 1
        summary.patched_codes["J05"] = summary.patched_codes.get("J05", 0) + 1
        delta += 1

    if not inserts:
        return out

    new_block = out[:insert_at] + "".join(inserts) + out[insert_at:]
    new_block = _update_num_frequencies(new_block, delta)
    return new_block


def _header_with_provenance(
    original_text: str,
    *,
    source_sha256: str,
    summary: PatchSummary,
) -> str:
    """Inject PNT Moni provenance COMMENT lines after the ANTEX header line.

    Preserves the first two ANTEX header lines (VERSION / SYST, PCV TYPE /
    REFANT) and inserts COMMENT records immediately after them. Existing
    upstream COMMENT lines are preserved.
    """
    # Find the second header line's end (PCV TYPE / REFANT or first
    # COMMENT). We insert right after the PCV TYPE / REFANT line.
    lines = original_text.splitlines(keepends=True)
    out: list[str] = []
    inserted = False
    for i, line in enumerate(lines):
        out.append(line)
        if not inserted and "PCV TYPE / REFANT" in line:
            # Insert provenance comments immediately after.
            stamp = "PNTMONI L5COPY DERIVATION".ljust(60)
            comments = [
                f"{stamp}COMMENT             \n",
                f"{'source: IGS20 igs20.atx'.ljust(60)}COMMENT             \n",
                f"{('source-sha256: ' + source_sha256[:32] + '...').ljust(60)}COMMENT             \n",
                f"{('algorithm-version: ' + ALGORITHM_VERSION).ljust(60)}COMMENT             \n",
                f"{('G05 inserts: ' + str(summary.n_g05_inserted)).ljust(60)}COMMENT             \n",
                f"{('J05 inserts: ' + str(summary.n_j05_inserted)).ljust(60)}COMMENT             \n",
                f"{('antennas seen: ' + str(summary.n_antennas_seen)).ljust(60)}COMMENT             \n",
                f"{'rule: copy F02 PCV to F05 when F05 missing'.ljust(60)}COMMENT             \n",
            ]
            out.extend(comments)
            inserted = True
    return "".join(out)


def build_l5copy(
    source_atx: Path,
    dest_atx: Path,
    *,
    source_sha256: str,
) -> PatchSummary:
    """Read ``source_atx``, patch it, write to ``dest_atx``.

    Returns a ``PatchSummary`` for logging/audit. Caller is responsible
    for recording the derived file's SHA-256 in provenance.
    """
    text = source_atx.read_text(encoding="utf-8")
    parts = _split_blocks(text)

    summary = PatchSummary()
    patched_parts: list[str] = []
    for i, part in enumerate(parts):
        if i % 2 == 1:
            patched_parts.append(_patch_block(part, summary))
        else:
            patched_parts.append(part)

    body = "".join(patched_parts)
    out_text = _header_with_provenance(body, source_sha256=source_sha256, summary=summary)
    dest_atx.parent.mkdir(parents=True, exist_ok=True)
    dest_atx.write_text(out_text, encoding="utf-8")
    logger.info(
        "L5copy: %d antennas seen, G05 inserts=%d, J05 inserts=%d → %s",
        summary.n_antennas_seen, summary.n_g05_inserted, summary.n_j05_inserted, dest_atx,
    )
    return summary
