"""Minimal failure notification for unattended runs.

Always logs. If ``PNTMONI_NTFY_URL`` is set (an ntfy.sh-style topic URL),
also POSTs the message there so a nightly launchd run can page the
founder on failure. Kept dependency-light (httpx is already a project
dep) and best-effort — notification never raises into the caller.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

NTFY_ENV = "PNTMONI_NTFY_URL"


def notify(title: str, body: str, *, priority: str = "default") -> None:
    """Emit a notification (log always; ntfy if configured)."""
    logger.warning("NOTIFY [%s] %s — %s", priority, title, body)
    url = os.environ.get(NTFY_ENV)
    if not url:
        return
    try:
        import httpx

        httpx.post(
            url,
            content=body.encode("utf-8"),
            headers={"Title": title, "Priority": priority, "Tags": "satellite"},
            timeout=10.0,
        )
    except Exception:  # noqa: BLE001 — notification is best-effort
        logger.exception("ntfy notification to %s failed", url)
