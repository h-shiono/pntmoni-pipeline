"""Locate and version-detect the ``rnx2rtkp`` binary."""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Search order for an unpacked CLASLIB tree (POSIX). The legacy upstream
# Makefile in ``util/rnx2rtkp/`` builds the binary in place; some forks
# build into ``bin/``. Override via the ``--binary`` CLI flag.
_DEFAULT_LOCATIONS = (
    Path("vendor/claslib/util/rnx2rtkp/rnx2rtkp"),
    Path("vendor/pntmoni-claslib/util/rnx2rtkp/rnx2rtkp"),
    Path("vendor/claslib/bin/rnx2rtkp"),
)


def find_binary(repo_root: Path | None = None) -> Path:
    """Return the path to a working ``rnx2rtkp`` binary or raise.

    The resolved path is the first existing candidate among
    ``_DEFAULT_LOCATIONS`` relative to ``repo_root`` (defaults to CWD).
    """
    base = (repo_root or Path.cwd()).resolve()
    for rel in _DEFAULT_LOCATIONS:
        candidate = base / rel
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "rnx2rtkp binary not found. Build CLASLIB first:\n"
        "  cd vendor/claslib/util/rnx2rtkp && make\n"
        f"Searched: {[str(base / p) for p in _DEFAULT_LOCATIONS]}"
    )


_VERSION_RE = re.compile(r"version[: ]+(\S+)", re.IGNORECASE)


def detect_version(binary: Path) -> str:
    """Best-effort version string from ``rnx2rtkp -h`` (CLASLIB embeds rev)."""
    try:
        proc = subprocess.run(
            [str(binary), "-h"],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return "unknown"
    blob = (proc.stdout or "") + (proc.stderr or "")
    m = _VERSION_RE.search(blob)
    return m.group(1) if m else "unknown"
