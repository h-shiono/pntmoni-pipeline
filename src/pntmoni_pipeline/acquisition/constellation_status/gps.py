"""GPS constellation status — USCG NAVCEN page.

Scrapes the constellation-status table at
``https://www.navcen.uscg.gov/gps-constellation``.

Table columns (as of mid-2026):
    Plane | Slot | SVN | PRN | Block-Type | Clock | Outage Start
    | NANU Type | NANU Subject

Status mapping:
    - Subject contains DECOMMISSION       → 'decommissioned'
    - NANU Type in {UNUSUFN, UNUSANO}     → 'unusable' (in-effect)
      or Subject contains UNUSABLE / UNAVAILABLE
    - Else                                → 'operational'
The NAVCEN page lists every active NANU including scheduled future
outages (FCSTSUMM / DELAYED). Treating those as "outage" misreads
"this satellite has a maintenance window scheduled" as "this satellite
is down right now". The notice details remain in notice_type /
notice_subject for the reader.
"""
from __future__ import annotations

from bs4 import BeautifulSoup
import pandas as pd

from . import _aggregate as _agg

URL = "https://www.navcen.uscg.gov/gps-constellation"

# The "constellation status" table is the one with >10 rows whose header
# row begins with "Plane".
_HEADER_HINT = "Plane"


def _select_table(soup: BeautifulSoup) -> "BeautifulSoup":
    for t in soup.find_all("table"):
        rows = t.find_all("tr")
        if not rows:
            continue
        hdr_cells = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        if hdr_cells and hdr_cells[0].startswith(_HEADER_HINT):
            return t
    raise RuntimeError("NAVCEN GPS constellation table not found")


def _status_for(notice_type: str, notice_subject: str) -> str:
    nt = (notice_type or "").upper()
    ns = (notice_subject or "").upper()
    if "DECOMMISSION" in ns:
        return "decommissioned"
    # "Unusable Until Further Notice" / "Unusable Notice" — currently down.
    if nt in {"UNUSUFN", "UNUSANO"} or "UNUSABLE" in ns or "UNAVAILABLE" in ns:
        return "unusable"
    return "operational"


def parse(html: str) -> pd.DataFrame:
    soup = BeautifulSoup(html, "html.parser")
    t = _select_table(soup)
    rows = t.find_all("tr")
    # Strip the descending-sort suffix the page injects into the header
    # ("SlotSort descending" → "Slot").
    headers = [
        c.get_text(strip=True).replace("Sort descending", "").replace("Sort ascending", "")
        for c in rows[0].find_all(["th", "td"])
    ]
    out: list[dict[str, object]] = []
    for r in rows[1:]:
        cells = [c.get_text(strip=True) for c in r.find_all(["th", "td"])]
        if len(cells) < len(headers):
            continue
        rec = dict(zip(headers, cells))
        prn_raw = rec.get("PRN", "")
        prn: int | None
        try:
            prn = int(prn_raw)
        except (TypeError, ValueError):
            prn = None
        plane = rec.get("Plane", "")
        slot = rec.get("Slot", "")
        out.append(_agg.make_row(
            constellation="gps",
            satellite_id=f"G{prn:02d}" if prn is not None else f"SVN{rec.get('SVN','')}",
            source_url=URL,
            svn=rec.get("SVN", ""),
            prn=prn,
            block=rec.get("Block-Type", ""),
            slot=f"{plane}{slot}".strip() or "",
            clock=rec.get("Clock", ""),
            status=_status_for(rec.get("NANU Type", ""), rec.get("NANU Subject", "")),
            signals="",                   # navcen doesn't list signals per-PRN
            notice_id=rec.get("NANU Type", "") and rec.get("NANU Subject", "")[:0] or "",
            notice_type=rec.get("NANU Type", ""),
            notice_subject=rec.get("NANU Subject", ""),
        ))
    return _agg.rows_to_frame(out)
