"""Tests for the monthly-report render driver (§7.4)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from pntmoni_pipeline import config_hash as ch
from pntmoni_pipeline.reports import driver as D


def _mk_parquet(p: Path, df: pd.DataFrame) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)


def test_gather_inputs_loads_present_and_skips_missing(tmp_path: Path):
    period, mode = "2026-04", "kinematic_p30_verify"
    root = tmp_path / "processed"
    _mk_parquet(
        root / "l6_alerts" / "2026" / "2026-04.parquet",
        pd.DataFrame({"date": ["2026-04-01"], "prn": [193], "tow": [0]}),
    )
    b = D.gather_inputs(period, mode, processed_root=root)
    assert b.l6_alerts is not None and len(b.l6_alerts) == 1
    assert b.accuracy_station is None and b.ttff_station is None
    st = b.status()
    assert st["l6_alerts"] == "present"
    assert st["accuracy_station"] == "missing"


def test_gather_inputs_rejects_bad_period():
    import pytest
    with pytest.raises(ValueError):
        D.gather_inputs("2026/04", "m")


def test_default_config_inputs_picks_mode_conf(tmp_path: Path):
    cfg = tmp_path / "configs"
    (cfg / "stations").mkdir(parents=True)
    (cfg / "default.toml").write_text("x=1\n")
    (cfg / "stations" / "s.toml").write_text("y=2\n")
    (cfg / "kinematic_p30_verify.conf").write_text("k=v\n")
    (cfg / "other.conf").write_text("z=1\n")
    tomls, confs = D.default_config_inputs(
        config_dir=cfg, mode="kinematic_p30_verify",
    )
    assert {p.name for p in tomls} == {"default.toml", "s.toml"}
    assert [p.name for p in confs] == ["kinematic_p30_verify.conf"]


def test_compute_monthly_config_hash_deterministic(tmp_path: Path):
    cfg = tmp_path / "configs"
    (cfg / "stations").mkdir(parents=True)
    (cfg / "default.toml").write_text("a=1\n")
    (cfg / "kinematic_p30_verify.conf").write_text("k=v\n")
    h1 = D.compute_monthly_config_hash(mode="kinematic_p30_verify", config_dir=cfg)
    h2 = D.compute_monthly_config_hash(mode="kinematic_p30_verify", config_dir=cfg)
    assert h1.full == h2.full and len(h1.full) == 64


def test_assemble_params_contains_required_fields(tmp_path: Path):
    b = D.InputsBundle(period="2026-04", mode="kinematic_p30_verify",
                       paths={"l6_alerts": tmp_path / "x.parquet"})
    p = D.assemble_params(
        period="2026-04", mode="kinematic_p30_verify", stream="final",
        inputs=b, config_hash_full="0" * 64,
    )
    assert p["year"] == 2026 and p["month"] == 4 and p["period"] == "2026-04"
    assert p["stream"] == "final" and p["data_mode"] == "live"
    assert p["methodology_version"] == "1.0.0"
    assert p["engine"] == "pntmoni-claslib"
    assert p["config_hash"] == "0" * ch.DISPLAY_LEN
    assert p["reference_coord_version"] == "gsi-daily-median15d-1.0"
    assert "l6_alerts" in p["inputs"] and "l6_alerts" in p["inputs_status"]


def test_run_monthly_no_render_writes_params_and_provenance(tmp_path: Path):
    cfg = tmp_path / "configs"
    (cfg / "stations").mkdir(parents=True)
    (cfg / "default.toml").write_text("a=1\n")
    (cfg / "kinematic_p30_verify.conf").write_text("k=v\n")
    processed = tmp_path / "processed"
    out_root = tmp_path / "reports"
    log = tmp_path / "processing.jsonl"

    res = D.run_monthly(
        period="2026-04", mode="kinematic_p30_verify", stream="final",
        template=Path("reports/templates/monthly.qmd"),
        output_root=out_root, processing_log=log,
        processed_root=processed, config_dir=cfg,
        do_render=False,
    )
    assert res.rendered is False
    assert res.params_path.is_file()
    params = json.loads(res.params_path.read_text())
    assert params["period"] == "2026-04"
    assert params["config_hash"] == res.config_hash_display
    assert log.is_file()
    rec = json.loads(log.read_text().strip().splitlines()[-1])
    assert rec["kind"] == "report_monthly"
    assert rec["config_hash_full"] == res.config_hash_full
    assert rec["rendered"] is False
