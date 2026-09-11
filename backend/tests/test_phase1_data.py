from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

from scripts.generate_synthetic_data import Config, SCENARIOS, generate, write, write_readme
from scripts.validate_synthetic_data import validate


def test_small_dataset_generation_and_validation(tmp_path: Path):
    out = tmp_path / "generated"
    cfg = Config(personnel=24, days=21, seed=11, output=out)
    frames = generate(cfg)
    write(frames, out)
    write_readme(out, cfg, frames)
    ok, errors, counts = validate(out, personnel_n=24, days=21)
    assert ok, errors
    assert counts["personnel.csv"] == 24
    assert counts["duty_events.csv"] > 0
    assert counts["deployment_events.csv"] > 0
    assert counts["leave_events.csv"] > 0
    assert counts["wellness_events.csv"] > 0


def test_same_seed_produces_identical_csv_bytes(tmp_path: Path):
    a, b = tmp_path / "a", tmp_path / "b"
    cfg_a = Config(personnel=18, days=15, seed=99, output=a)
    cfg_b = Config(personnel=18, days=15, seed=99, output=b)
    frames_a=generate(cfg_a); frames_b=generate(cfg_b)
    write(frames_a, a); write_readme(a, cfg_a, frames_a)
    write(frames_b, b); write_readme(b, cfg_b, frames_b)
    for name in (
        "personnel.csv", "units.csv", "duty_events.csv", "recovery_events.csv",
        "leave_events.csv", "deployment_events.csv", "training_events.csv",
        "incident_events.csv", "wellness_events.csv",
    ):
        assert hashlib.sha256((a/name).read_bytes()).digest() == hashlib.sha256((b/name).read_bytes()).digest()


def test_foreign_keys_and_temporal_relationships(tmp_path: Path):
    out = tmp_path / "generated"
    cfg=Config(personnel=30, days=30, seed=7, output=out)
    frames=generate(cfg); write(frames, out); write_readme(out, cfg, frames)
    p = pd.read_csv(out / "personnel.csv")
    u = pd.read_csv(out / "units.csv")
    d = pd.read_csv(out / "duty_events.csv")
    dep = pd.read_csv(out / "deployment_events.csv")
    lv = pd.read_csv(out / "leave_events.csv")
    assert set(p.unit_id) <= set(u.unit_id)
    assert set(d.person_id) <= set(p.person_id)
    nonblank = set(d["deployment_id"].fillna("").astype(str)); nonblank.discard(""); nonblank.discard("nan")
    assert nonblank <= set(dep.deployment_event_id)
    if len(dep):
        starts=pd.to_datetime(dep.start_date); ends=pd.to_datetime(dep.end_date)
        assert (starts<=ends).all()
    if len(lv):
        starts=pd.to_datetime(lv.start_date); ends=pd.to_datetime(lv.end_date)
        assert (starts<=ends).all()
        assert (lv.duration_days == (ends-starts).dt.days+1).all()
    assert set(SCENARIOS) == {"STABLE","HIGH_LOAD","RECOVERY_DEFICIT","PROLONGED_DEPLOYMENT","VOLATILE","RECOVERY_AFTER_PEAK"}
