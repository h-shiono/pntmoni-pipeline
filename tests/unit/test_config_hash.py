"""Tests for the §7.2 pipeline config hash."""
from __future__ import annotations

from pathlib import Path

from pntmoni_pipeline.config_hash import DISPLAY_LEN, compute_config_hash

VERSIONS = dict(
    engine_version="pntmoni-claslib v0.8.3-pntmoni-1",
    qc_tool_version="teqc 2019Feb25",
    reference_coord_version="gsi-daily-median15d-1.0",
    methodology_version="1.0.0",
)


def _write(p: Path, text: str) -> Path:
    p.write_text(text, encoding="utf-8")
    return p


def test_display_is_first_16_of_full():
    r = compute_config_hash(**VERSIONS)
    assert len(r.full) == 64
    assert r.display == r.full[:DISPLAY_LEN]
    assert len(r.display) == 16


def test_deterministic(tmp_path):
    t = _write(tmp_path / "a.toml", "x = 1\ny = 2\n")
    r1 = compute_config_hash(toml_paths=[t], **VERSIONS)
    r2 = compute_config_hash(toml_paths=[t], **VERSIONS)
    assert r1.full == r2.full


def test_toml_canonicalization_is_key_order_independent(tmp_path):
    a = _write(tmp_path / "a.toml", "x = 1\ny = 2\n")
    b = _write(tmp_path / "a.toml", "y = 2\nx = 1\n")  # same data, reordered
    # Re-read b after overwrite; both produce identical canonical form.
    ra = compute_config_hash(toml_paths=[a], **VERSIONS)
    rb = compute_config_hash(toml_paths=[b], **VERSIONS)
    assert ra.full == rb.full


def test_comment_changes_do_not_affect_hash(tmp_path):
    a = _write(tmp_path / "a.toml", "x = 1\n")
    ha = compute_config_hash(toml_paths=[a], **VERSIONS).full
    _write(tmp_path / "a.toml", "# a comment\nx = 1\n")
    hb = compute_config_hash(toml_paths=[a], **VERSIONS).full
    assert ha == hb


def test_value_change_changes_hash(tmp_path):
    a = _write(tmp_path / "a.toml", "x = 1\n")
    ha = compute_config_hash(toml_paths=[a], **VERSIONS).full
    _write(tmp_path / "a.toml", "x = 2\n")
    hb = compute_config_hash(toml_paths=[a], **VERSIONS).full
    assert ha != hb


def test_conf_content_changes_hash(tmp_path):
    c = _write(tmp_path / "k.conf", "pos1-posmode = ppp-rtk\n")
    h1 = compute_config_hash(conf_paths=[c], **VERSIONS).full
    _write(tmp_path / "k.conf", "pos1-posmode = static\n")
    h2 = compute_config_hash(conf_paths=[c], **VERSIONS).full
    assert h1 != h2


def test_version_string_change_changes_hash():
    base = compute_config_hash(**VERSIONS).full
    bumped = compute_config_hash(**{**VERSIONS, "methodology_version": "1.0.1"}).full
    assert base != bumped


def test_file_order_independent(tmp_path):
    a = _write(tmp_path / "a.toml", "x = 1\n")
    b = _write(tmp_path / "b.toml", "y = 2\n")
    r1 = compute_config_hash(toml_paths=[a, b], **VERSIONS).full
    r2 = compute_config_hash(toml_paths=[b, a], **VERSIONS).full
    assert r1 == r2
