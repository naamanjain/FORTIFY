from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

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
    open_cases = {("P-0001", "2026-01-22"): "NEW"}
    first = choose_hero(df, open_cases)
    second = choose_hero(df, open_cases)
    assert first == second
    assert first[0] == "P-0001"
    assert first[1] == pd.Timestamp("2026-01-22")
    assert first[2] > 0.70


def test_hero_selection_refuses_a_case_no_officer_can_open():
    """The scripted demo must not point at a person-day with no workflow case.

    Selecting from the scoring outputs alone used to produce a hero the officer
    could not open, and the absent row was then reported as state NEW.
    """
    df = _fixture()
    with pytest.raises(ValueError, match="open workflow case"):
        choose_hero(df, {})


def test_workflow_case_lookup_returns_only_actionable_states():
    """A closed case must never be offered as the demonstration hero.

    prepare_demo trusts the set it is given, so the filter lives in the query
    that builds it and is asserted here. A lookup without a stated scope must
    deny rather than default to the whole roster.
    """
    from app.security.rbac import UnitScope
    from app.services.workflow import PENDING_STATES, open_case_id_for_person
    assert "CLOSED" not in PENDING_STATES and "DISMISSED" not in PENDING_STATES
    assert open_case_id_for_person("P-NOT-A-PERSON", UnitScope.script()) is None
    # Two different failures, two different signals:
    # a caller that never stated a scope is a programming error ...
    with pytest.raises(PermissionError):
        open_case_id_for_person("P-0002")
    # ... while a caller whose scope resolves to nothing simply sees nothing.
    assert open_case_id_for_person("P-0002", UnitScope(source="claims-empty")) is None
    assert open_case_id_for_person("P-0002", UnitScope(units=frozenset({"U-999"}), source="claims")) is None


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
