"""Locate and version-detect the ``rnx2rtkp`` binary."""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Search order for an unpacked CLASLIB tree (POSIX). Per ADR 0004 the
# active engine is `pntmoni-claslib`; the upstream `claslib` path is
# kept as a fallback for environments still on the pre-fork submodule.
# Override via the ``--binary`` CLI flag.
_DEFAULT_LOCATIONS = (
    Path("vendor/pntmoni-claslib/util/rnx2rtkp/rnx2rtkp"),
    Path("vendor/pntmoni-claslib/bin/rnx2rtkp"),
    Path("vendor/claslib/util/rnx2rtkp/rnx2rtkp"),
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
        "rnx2rtkp binary not found. Build the engine first:\n"
        "  cd vendor/pntmoni-claslib/util/rnx2rtkp && make\n"
        f"Searched: {[str(base / p) for p in _DEFAULT_LOCATIONS]}"
    )


_VERSION_RE = re.compile(r"version[: ]+(\S+)", re.IGNORECASE)


def _git_describe(working_dir: Path) -> str | None:
    """Return ``git describe --tags --always`` for ``working_dir`` or None."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(working_dir), "describe", "--tags", "--always", "--dirty"],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    out = (proc.stdout or "").strip()
    return out or None


def detect_version(binary: Path) -> str:
    """Best-effort engine version.

    First tries ``rnx2rtkp -h`` for an embedded version string. If the
    binary does not advertise one, falls back to ``git describe`` on the
    submodule directory the binary was built in (e.g. yields
    ``v0.8.3-pntmoni-1`` for the fork-tagged release).
    """
    try:
        proc = subprocess.run(
            [str(binary), "-h"],
            capture_output=True, text=True, timeout=5,
        )
        blob = (proc.stdout or "") + (proc.stderr or "")
        m = _VERSION_RE.search(blob)
        if m:
            return m.group(1)
    except (subprocess.TimeoutExpired, OSError):
        pass

    # Walk up to the submodule root (.git presence) for git describe.
    candidate = binary.resolve().parent
    for _ in range(6):
        if (candidate / ".git").exists():
            described = _git_describe(candidate)
            if described:
                return described
            break
        if candidate.parent == candidate:
            break
        candidate = candidate.parent

    return "unknown"
