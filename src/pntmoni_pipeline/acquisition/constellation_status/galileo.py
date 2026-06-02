"""Galileo constellation status — GSC Europa page.

Scrapes the constellation table at
``https://www.gsc-europa.eu/system-service-status/constellation-information``.

Table columns (as of mid-2026):
    Satellite Name | SV ID | Clock | Status | Active NAGU
    | NAGU Type | NAGU Subject

Status vocabulary in the source is already close to canonical
(`USABLE`, `NOT USABLE`, `COMMISSIONING`, `TESTING`) — normalised via
``_aggregate.normalize_status``.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup
import pandas as pd

from . import _aggregate as _agg

URL = "https://www.gsc-europa.eu/system-service-status/constellation-information"


def _select_table(soup: BeautifulSoup) -> "BeautifulSoup":
    """Pick the table whose header contains 'Satellite Name' and 'SV ID'."""
    for t in soup.find_all("table"):
        rows = t.find_all("tr")
        if not rows:
            continue
        hdr = " ".join(c.get_text(strip=True) for c in rows[0].find_all(["th", "td"]))
        if "Satellite Name" in hdr and "SV ID" in hdr:
            return t
    raise RuntimeError("GSC Galileo constellation table not found")


def _strip_footnote(s: str) -> str:
    """'Satellite Name1' → 'Satellite Name'; numerical superscripts."""
    return re.sub(r"\d+$", "", s).strip()


def parse(html: str) -> pd.DataFrame:
    soup = BeautifulSoup(html, "html.parser")
    t = _select_table(soup)
    rows = t.find_all("tr")
    headers = [_strip_footnote(c.get_text(strip=True))
               for c in rows[0].find_all(["th", "td"])]
    out: list[dict[str, object]] = []
    for r in rows[1:]:
        cells = [c.get_text(strip=True) for c in r.find_all(["th", "td"])]
        if len(cells) < len(headers):
            continue
        rec = dict(zip(headers, cells))
        sat_name = rec.get("Satellite Name", "")     # 'GSAT0101'
        sv_id = rec.get("SV ID", "")                  # 'E11'
        # PRN = numeric tail of SV ID ('E11' → 11). Galileo PRNs are 1-36.
        prn: int | None
        m = re.search(r"(\d+)", sv_id)
        try:
            prn = int(m.group(1)) if m else None
        except ValueError:
            prn = None
        out.append(_agg.make_row(
            constellation="gal",
            satellite_id=sv_id or sat_name,
            source_url=URL,
            svn=sat_name,                              # 'GSAT0101' is Galileo's SVN
            prn=prn,
            block="",                                  # not in table
            slot="",                                   # need separate orbital params page
            clock=rec.get("Clock", ""),
            status=_agg.normalize_status(rec.get("Status", "")),
            signals="",                                # signal availability not in table
            notice_id=rec.get("Active NAGU", ""),
            notice_type=rec.get("NAGU Type", ""),
            notice_subject=rec.get("NAGU Subject", ""),
        ))
    return _agg.rows_to_frame(out)
