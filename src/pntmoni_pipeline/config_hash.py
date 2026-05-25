"""Pipeline-level config hash (methodology §7.2).

A single SHA-256 that identifies a reproducible processing
configuration for a report run. It is concatenated from, in order:

1. Canonicalized TOML configs — parsed with ``tomllib`` then
   re-serialized with sorted keys (comments dropped by the parse),
   in lexicographic path order.
2. CLASLIB ``.conf`` files — these are *not* TOML, so each
   contributes ``conf:<name>:<sha256-of-raw-bytes>`` in lexicographic
   path order.
3. Engine version string (e.g. ``pntmoni-claslib v0.8.3-pntmoni-1``).
4. QC tool version string (e.g. ``teqc 2019Feb25``).
5. Reference-coordinate methodology version
   (e.g. ``gsi-daily-median15d-1.0``).
6. Methodology version (e.g. ``1.0.0``).

The 64-hex digest's first :data:`DISPLAY_LEN` chars are shown in the
monthly report footer (§7.4); the full digest is recorded in
``processing.jsonl`` (§7.3).
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:                                                 # pragma: no cover
    import tomli as tomllib

DISPLAY_LEN = 16


@dataclass(frozen=True)
class ConfigHashResult:
    """Result of :func:`compute_config_hash`.

    ``full`` is the 64-hex SHA-256; ``display`` is its first
    :data:`DISPLAY_LEN` characters (report footer); ``components`` maps
    each input to a compact per-component digest/value for audit.
    """

    full: str
    components: dict[str, str] = field(default_factory=dict)

    @property
    def display(self) -> str:
        return self.full[:DISPLAY_LEN]


def _canonical_toml(path: Path) -> str:
    """Return a canonical JSON string of a TOML file (sorted keys)."""
    with path.open("rb") as f:
        data = tomllib.load(f)
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, default=str,
    )


def _sha256_bytes(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def compute_config_hash(
    *,
    engine_version: str,
    qc_tool_version: str,
    reference_coord_version: str,
    methodology_version: str,
    toml_paths: Sequence[Path] = (),
    conf_paths: Sequence[Path] = (),
) -> ConfigHashResult:
    """Compute the §7.2 pipeline config hash over the given inputs.

    ``toml_paths`` are canonicalized (key order does not affect the
    hash); ``conf_paths`` are hashed by raw content. The four version
    strings are appended verbatim. Ordering of files is lexicographic
    by path so the digest is independent of argument order.
    """
    parts: list[str] = []
    components: dict[str, str] = {}

    for p in sorted(toml_paths, key=lambda x: str(x)):
        canon = _canonical_toml(p)
        parts.append(f"toml:{p.name}:{canon}")
        components[f"toml:{p.name}"] = hashlib.sha256(canon.encode("utf-8")).hexdigest()

    for p in sorted(conf_paths, key=lambda x: str(x)):
        digest = _sha256_bytes(p)
        parts.append(f"conf:{p.name}:{digest}")
        components[f"conf:{p.name}"] = digest

    for label, val in (
        ("engine_version", engine_version),
        ("qc_tool_version", qc_tool_version),
        ("reference_coord_version", reference_coord_version),
        ("methodology_version", methodology_version),
    ):
        parts.append(f"{label}:{val}")
        components[label] = val

    blob = "\n".join(parts).encode("utf-8")
    full = hashlib.sha256(blob).hexdigest()
    return ConfigHashResult(full=full, components=components)


__all__ = ["DISPLAY_LEN", "ConfigHashResult", "compute_config_hash"]
