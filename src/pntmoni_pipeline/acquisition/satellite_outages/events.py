"""Normalise raw notices into ``OutageEvent`` records.

Methodology version: ``outage-norm-v1``. See
``pntmoni-docs/40-data-schemas/satellite-outages.md`` for the rules
this module implements.

Rule summary:

1. Cluster raw notices by ``(constellation, SVN, event-identity)``.
   - For NANU / NAQU: an event chain is identified by the
     ``REFERENCE`` header. A notice with REFERENCE = N/A starts a new
     chain; a notice citing a previous number joins that chain.
   - For NAGU: the same applies — the ``NAGU REFERENCED TO`` field
     points at the predecessor (or N/A for a new chain).
2. Resolve event window:
   - ``start_at`` = earliest ``effective_at`` across the chain
   - ``end_at`` = latest ``expires_at`` from notices that report a
     concrete end (NULL if every chain member is open-ended, e.g.
     a decommissioning chain)
3. Classify ``event_type`` via keyword matching on the notice TYPE
   labels (e.g. ``FCSTDV`` → scheduled_maintenance, ``UNUSABLE`` →
   unscheduled_outage, ``DECOM`` → decommissioning, ``USABLE`` →
   health_change).
4. Determine ``severity`` (``total`` / ``partial`` / ``informational``)
   from signal-affected metadata when present, else from the type label.
5. ``event_id`` is deterministic: ``{constellation}:{svn:03d}:{first_published_at:YYYYMMDD}:{root_number}``
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Iterable

from ._models import OutageEvent, RawNotice

logger = logging.getLogger(__name__)

METHODOLOGY_VERSION = "outage-norm-v1"

# Keyword → event_type mapping. Substring match against the upstream
# TYPE label (case-insensitive). First match wins.
_TYPE_MAP: tuple[tuple[str, str], ...] = (
    ("DECOM", "decommissioning"),
    ("FCST", "scheduled_maintenance"),    # FCSTDV / FCSTSUMM / FCSTCANC
    ("PLN_OUTAGE", "scheduled_maintenance"),
    ("MAINT", "scheduled_maintenance"),
    ("UNUSABLE", "unscheduled_outage"),
    ("UNUNOREF", "unscheduled_outage"),
    ("UNAVAIL", "unscheduled_outage"),
    ("USABLE", "health_change"),
    ("HEALTH", "health_change"),
    ("GENERAL", "other"),
    ("HAS", "frequency_outage"),
)

# "Partial" signals — when these tokens appear in the type, we assume a
# specific signal/family is affected rather than the full SV.
_PARTIAL_TOKENS = ("L1S", "L6", "L1C/B", "L2", "L5", "DCR", "DCX", "MDC", "HAS")


def _classify_event_type(type_label: str) -> str:
    upper = type_label.upper()
    for token, cls in _TYPE_MAP:
        if token in upper:
            return cls
    return "other"


def _classify_severity(notice: RawNotice) -> str:
    upper = (notice.notice_type or "").upper()
    if "USABLE" in upper and "UNUSABLE" not in upper:
        return "informational"
    if "GENERAL" in upper:
        return "informational"
    # NAGU: SIGNALS AFFECTED == "ALL" → total; otherwise partial.
    signals = notice.extras.get("signals_affected") or ""
    if signals and signals.strip().upper() != "ALL":
        return "partial"
    # NANU/NAQU: type prefix like "L6_..." indicates partial.
    if any(t in upper for t in _PARTIAL_TOKENS):
        return "partial"
    return "total"


def _chain_root(notices: dict[str, RawNotice], notice_id: str) -> str:
    """Walk the REFERENCE chain to its root (earliest notice)."""
    seen: set[str] = set()
    current = notice_id
    while current in notices and current not in seen:
        seen.add(current)
        ref_id = notices[current].extras.get("reference_id")
        if not ref_id:
            return current
        # NANU/NAQU reference is the 7-digit number; rebuild canonical ID.
        canonical = _canonical_id(notices[current].constellation, ref_id)
        if canonical not in notices:
            return current
        current = canonical
    return current


def _canonical_id(constellation: str, number: str) -> str:
    prefix = {"gps": "NANU", "gal": "NAGU", "qzs": "NAQU"}.get(constellation, "")
    return f"{prefix} {number}"


def _affected_signals(notice: RawNotice) -> list[str] | None:
    """Return the list of affected signals if not 'all', else None."""
    raw = notice.extras.get("signals_affected")
    if isinstance(raw, str):
        cleaned = raw.strip().upper()
        if not cleaned or cleaned == "ALL":
            return None
        return [s.strip() for s in cleaned.split(",") if s.strip()]
    # NAQU encodes the signal in NAQ_SS_SIGNAL; surface it as a single-elem list.
    naq_signal = notice.extras.get("naq_ss_signal")
    if isinstance(naq_signal, str) and naq_signal.upper() not in ("PNT", "ALL", ""):
        return [naq_signal]
    return None


def normalize(raw_notices: Iterable[RawNotice]) -> list[OutageEvent]:
    """Group ``raw_notices`` into chains and emit one OutageEvent per chain."""
    notices = {n.notice_id: n for n in raw_notices}
    if not notices:
        return []

    # Map each notice to its chain root.
    chain_map: dict[str, str] = {nid: _chain_root(notices, nid) for nid in notices}

    # Bucket by chain root.
    chains: dict[str, list[RawNotice]] = defaultdict(list)
    for nid, root in chain_map.items():
        chains[root].append(notices[nid])

    events: list[OutageEvent] = []
    for root_id, members in chains.items():
        members_sorted = sorted(members, key=lambda n: n.published_at)
        head = members_sorted[0]
        tail = members_sorted[-1]

        # SVN: take from any member that records one (typically all
        # NANU/NAQU members; NAGU may have only space_vehicle_id).
        svn = next((n.svn for n in members_sorted if n.svn is not None), None)
        if svn is None:
            svn = next(
                (n.extras.get("space_vehicle_id") for n in members_sorted
                 if isinstance(n.extras.get("space_vehicle_id"), int)),
                None,
            )
        if svn is None:
            # Cannot anchor to a satellite — skip with a warning. This
            # happens for general-notice NAGUs that affect "ALL".
            logger.debug("skipping chain root=%s: no SVN in any member", root_id)
            svn = 0  # sentinel so the row still serialises; UI can hide.

        prn = next((n.prn for n in members_sorted if n.prn is not None), None)

        start_at = min(
            (n.effective_at for n in members_sorted if n.effective_at is not None),
            default=head.published_at,
        )
        end_at = max(
            (n.expires_at for n in members_sorted if n.expires_at is not None),
            default=None,
        )

        # Event type from the head's type label is the most stable.
        event_type = _classify_event_type(head.notice_type or "")
        severity = _classify_severity(tail)  # tail = latest known state

        signals = _affected_signals(tail)
        reason = (
            tail.extras.get("event_description")
            or tail.extras.get("condition")
            or tail.extras.get("subject")
            or None
        )

        # event_id: deterministic, sortable.
        first_iso = head.published_at.strftime("%Y%m%d")
        root_number = head.notice_id.split()[-1] if head.notice_id else "unknown"
        event_id = f"{head.constellation}:{int(svn):03d}:{first_iso}:{root_number}"

        is_active = end_at is None or tail.expires_at is None

        events.append(
            OutageEvent(
                event_id=event_id,
                constellation=head.constellation,
                svn=int(svn),
                prn=int(prn) if prn is not None else None,
                block=None,  # filled in later when SVN→block lookup table lands
                start_at=start_at,
                end_at=end_at,
                event_type=event_type,
                severity=severity,
                affected_signals=signals,
                reason=reason,
                source_notice_ids=[n.notice_id for n in members_sorted],
                first_published_at=head.published_at,
                last_updated_at=tail.published_at,
                is_active_at_publish=is_active,
            )
        )

    events.sort(key=lambda e: (e.first_published_at, e.constellation, e.svn))
    logger.info("normalised %d notices → %d events", len(notices), len(events))
    return events
