"""Workspace setup for ``rnx2rtkp``.

CLASLIB's ``rnx2rtkp`` resolves ``data/...`` paths from its config
relative to the current working directory. We give it a workspace
that contains:

- The ``rnx2rtkp`` binary (symlinked)
- A ``data/`` directory with auxiliary files (symlinked)
- The mode template config (copied — per-station configs override it)
- A decompressed shared BRDC + next-day BRDC + L6 file
- Per-station decompressed obs files (created by callers)

We use symlinks for read-only artefacts to avoid duplicating ~50 MB
of aux data across runs; obs/brdc are decompressed (rnx2rtkp does
not natively read .gz inputs).
"""
from __future__ import annotations

import gzip
import logging
import os
import shutil
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)


def _link_or_copy(src: Path, dst: Path, *, force: bool = False) -> Path:
    """Create or refresh a symlink at ``dst`` pointing at ``src``."""
    src = src.resolve()
    if dst.is_symlink() or dst.exists():
        if force:
            dst.unlink()
        else:
            return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(src, dst)
    except OSError:
        # Fallback for filesystems that do not support symlinks.
        shutil.copy2(src, dst)
    return dst


def gunzip_to(src_gz: Path, dst: Path, *, overwrite: bool = False) -> Path:
    """Decompress a ``.gz`` file to ``dst`` (idempotent)."""
    if dst.exists() and not overwrite:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".partial")
    try:
        with gzip.open(src_gz, "rb") as fin, tmp.open("wb") as fout:
            shutil.copyfileobj(fin, fout, length=1024 * 1024)
        shutil.move(str(tmp), str(dst))
    except BaseException:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise
    return dst


def setup(
    workspace: Path,
    *,
    binary: Path,
    data_dir: Path,
    mode_config: Path,
) -> None:
    """Populate the workspace with binary, ``data/``, and the mode config."""
    workspace.mkdir(parents=True, exist_ok=True)

    _link_or_copy(binary, workspace / binary.name, force=True)
    # Make sure binary is executable (no-op for symlinks if target is executable).
    target_bin = workspace / binary.name
    if not target_bin.is_symlink():
        os.chmod(target_bin, 0o755)

    # Symlink the data/ directory wholesale so all aux files are reachable.
    data_link = workspace / "data"
    if data_link.is_symlink() or data_link.exists():
        if data_link.is_symlink():
            data_link.unlink()
        elif data_link.is_dir():
            shutil.rmtree(data_link)
        else:
            data_link.unlink()
    try:
        os.symlink(data_dir.resolve(), data_link)
    except OSError:
        shutil.copytree(data_dir, data_link)

    # Copy the mode template (callers will write per-station overrides).
    shutil.copy2(mode_config, workspace / mode_config.name)


@contextmanager
def cleanup_partials(workspace: Path):
    """Remove leftover ``*.partial`` after a (failed or successful) run."""
    try:
        yield
    finally:
        for p in workspace.glob("*.partial"):
            p.unlink(missing_ok=True)
