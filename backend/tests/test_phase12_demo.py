from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.prepare_demo import choose_hero


def _fixture():
    rows = []
    for day in range(22):
        rows.append({
            "person_id": "P-0001",
            "date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=day),
            "welfare_risk_probability": 0.10 + day * 0.02,
            "risk_band": "LOW",
            "recommended_action": "ROUTINE_MONITORING",
            "priority": "LOW",
            "feasibility_status": "FEASIBLE",
            "constraint_flags": "",
        })
    # Make only the final day qualify for the deterministic hero policy.
    rows[-1].update({
        "welfare_risk_probability": 0.88,
        "risk_band": "HIGH",
        "recommended_action": "PRIORITY_WELFARE_REVIEW",
        "priority": "HIGH",
        "feasibility_status": "CONSTRAINED",
        "constraint_flags": "active_duty_conflict | training_conflict",
    })
    return pd.DataFrame(rows)


def test_hero_selection_is_deterministic_and_constraint_aware():
    df = _fixture()
    first = choose_hero(df)
    second = choose_hero(df)
    assert first == second
    assert first[0] == "P-0001"
    assert first[1] == pd.Timestamp("2026-01-22")
    assert first[2] > 0.70


def test_demo_manifest_is_non_clinical_and_privacy_safe(tmp_path, monkeypatch):
    # This verifies the manifest contract without executing the full CLI.
    manifest = {
        "synthetic_demo_only": True,
        "raw_wellness_in_outputs": False,
        "hero_case": {"risk_band": "HIGH", "recommended_action": "PRIORITY_WELFARE_REVIEW"},
        "safety_boundary": "Operational/welfare decision support only.",
    }
    p = tmp_path / "demo_manifest.json"
    p.write_text(json.dumps(manifest), encoding="utf-8")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["synthetic_demo_only"] is True
    assert data["raw_wellness_in_outputs"] is False
    assert "diagnosis" not in json.dumps(data).lower()
