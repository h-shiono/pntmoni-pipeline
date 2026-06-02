"""QZSS constellation status — QSS DoD page.

Scrapes ``https://sys.qzss.go.jp/dod/en/constellation.html``.

The page nests *per-service* rows under each satellite (a colspan=5
header row like ``QZS02 (SVN=002, Block type=Ⅱ-Q)`` followed by N
service rows: ``PNT``, ``SLAS``, ``CLAS`` etc.). We pivot to one
row per satellite where:
    - prn = the PRN of the PNT service (primary positioning signal)
    - signals = comma-joined "Positioning Signals" across all services
    - notice_id = NAQU number from any service row (if present)
    - status = 'outage' if any service reports non-O Operation, else
               'operational'
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup
import pandas as pd

from . import _aggregate as _agg

URL = "https://sys.qzss.go.jp/dod/en/constellation.html"

_SAT_HEADER_RE = re.compile(
    r"(?P<name>QZS\w+)\s*\(SVN=(?P<svn>\d+),\s*Block type=(?P<block>[^)]+)\)",
    re.IGNORECASE,
)


def _select_table(soup: BeautifulSoup) -> "BeautifulSoup":
    """Pick the constellation status table (header has 'Services'+'PRN')."""
    for t in soup.find_all("table"):
        rows = t.find_all("tr")
        if not rows:
            continue
        hdr = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        if "Services" in hdr and "PRN" in hdr:
            return t
    raise RuntimeError("QZSS DoD constellation table not found")


def parse(html: str) -> pd.DataFrame:
    soup = BeautifulSoup(html, "html.parser")
    t = _select_table(soup)
    rows = t.find_all("tr")
    out: list[dict[str, object]] = []
    current: dict | None = None

    for r in rows[1:]:                              # skip header
        cells = r.find_all(["th", "td"])
        if len(cells) == 1:
            # Satellite-header row (single colspan=5 cell).
            txt = cells[0].get_text(strip=True)
            m = _SAT_HEADER_RE.search(txt)
            if not m:
                continue
            if current is not None:
                out.append(current)
            current = {
                "name": m.group("name"),
                "svn":  m.group("svn"),
                "block": m.group("block").strip(),
                "pnt_prn": None,
                "signals": [],
                "operation_codes": set(),
                "naqu_numbers": [],
            }
            continue

        if current is None:
            continue
        vals = [c.get_text(strip=True) for c in cells]
        if len(vals) < 5:
            continue
        service, signals, prn_str, op, naqu = vals[:5]
        current["signals"].append(signals)
        current["operation_codes"].add(op)
        if naqu:
            current["naqu_numbers"].append(naqu)
        if service.upper() == "PNT" and current["pnt_prn"] is None:
            try:
                # PRNs sometimes carry footnote markers like "137(*1)".
                current["pnt_prn"] = int(re.match(r"\d+", prn_str).group(0))
            except (AttributeError, ValueError):
                current["pnt_prn"] = None

    if current is not None:
        out.append(current)

    # Pivot to row-per-satellite.
    rows_out: list[dict[str, object]] = []
    for s in out:
        ops = s["operation_codes"]
        status = "operational" if ops <= {"O", ""} else "outage"
        signals = []
        for sig_list in s["signals"]:
            for sig in (x.strip() for x in sig_list.split(",")):
                if sig and sig not in signals:
                    signals.append(sig)
        rows_out.append(_agg.make_row(
            constellation="qzs",
            satellite_id=f"J{s['pnt_prn']}" if s["pnt_prn"] is not None else s["name"],
            source_url=URL,
            svn=s["svn"],
            prn=s["pnt_prn"],
            block=s["block"],
            slot="",                              # not in this page
            clock="",
            status=status,
            signals=signals,
            notice_id=", ".join(s["naqu_numbers"]),
            notice_type="NAQU" if s["naqu_numbers"] else "",
            notice_subject="",
        ))
    return _agg.rows_to_frame(rows_out)
