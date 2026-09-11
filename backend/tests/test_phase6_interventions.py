from __future__ import annotations

import pandas as pd
import pytest

from backend.app.ml.intervention_config import InterventionPolicyConfig
from backend.app.ml.intervention_policy import build_intervention_recommendations, validate_intervention_output


def _row(person: str, date: str, band: str, probability: float, **kwargs):
    base = {
        "person_id": person,
        "date": date,
        "risk_band": band,
        "welfare_risk_probability": probability,
        "threshold_decision": "EARLY_WARNING" if probability >= 0.25 else "NO_EARLY_WARNING",
        "model_version": "phase5-v1",
    }
    base.update(kwargs)
    return base


def test_low_risk_maps_to_routine_monitoring() -> None:
    output = build_intervention_recommendations(pd.DataFrame([_row("P-1", "2026-01-01", "LOW", 0.10)]))
    assert output.loc[0, "recommended_action"] == "ROUTINE_MONITORING"
    assert output.loc[0, "priority"] == "LOW"
    assert bool(output.loc[0, "requires_human_review"]) is False


def test_moderate_recovery_context_gets_recovery_support() -> None:
    output = build_intervention_recommendations(pd.DataFrame([_row("P-1", "2026-01-01", "MODERATE", 0.35)]), pd.DataFrame([{
        "person_id": "P-1", "date": "2026-01-01", "avg_rest_7d": 6.5
    }]))
    assert output.loc[0, "recommended_action"] == "RECOVERY_SUPPORT"
    assert bool(output.loc[0, "requires_human_review"]) is True


def test_high_risk_maps_to_priority_welfare_review() -> None:
    output = build_intervention_recommendations(pd.DataFrame([_row("P-1", "2026-01-01", "HIGH", 0.80)]))
    assert output.loc[0, "recommended_action"] == "PRIORITY_WELFARE_REVIEW"
    assert output.loc[0, "priority"] == "HIGH"


def test_personal_baseline_aware_rationale_uses_existing_signal() -> None:
    output = build_intervention_recommendations(pd.DataFrame([_row(
        "P-1", "2026-01-01", "MODERATE", 0.35,
        contributing_operational_signals="Contributing operational signal: elevated recent duty hours (+3.2 hours vs personal reference).",
    )]))
    assert "personal reference" in output.loc[0, "rationale"]
    assert "associated" not in output.loc[0, "rationale"].lower() or "signals" in output.loc[0, "rationale"].lower()


def test_cooldown_suppresses_repeated_action() -> None:
    predictions = pd.DataFrame([
        _row("P-1", "2026-01-01", "MODERATE", 0.35),
        _row("P-1", "2026-01-02", "MODERATE", 0.36),
    ])
    output = build_intervention_recommendations(predictions)
    assert output.loc[0, "recommended_action"] == "WELLNESS_CHECK_IN"
    assert output.loc[1, "recommended_action"] == "CONTINUE_EXISTING_SUPPORT"


def test_material_risk_increase_breaks_cooldown() -> None:
    predictions = pd.DataFrame([
        _row("P-1", "2026-01-01", "MODERATE", 0.35),
        _row("P-1", "2026-01-02", "HIGH", 0.55),
    ])
    output = build_intervention_recommendations(predictions)
    assert output.loc[1, "recommended_action"] == "PRIORITY_WELFARE_REVIEW"


def test_missing_context_does_not_crash() -> None:
    predictions = pd.DataFrame([_row("P-1", "2026-01-01", "MODERATE", 0.35)])
    output = build_intervention_recommendations(predictions, pd.DataFrame([{"person_id": "P-1", "date": "2026-01-01"}]))
    assert output.loc[0, "recommended_action"] in {"WELLNESS_CHECK_IN", "SUPERVISOR_WELFARE_REVIEW", "RECOVERY_SUPPORT"}


def test_safety_and_schema_validation() -> None:
    output = build_intervention_recommendations(pd.DataFrame([_row("P-1", "2026-01-01", "HIGH", 0.8)]))
    validate_intervention_output(output)
    assert not any("perceived_stress" in c.lower() for c in output.columns)
    assert all("medical" not in str(x).lower() for x in output["rationale"])
    assert all("disciplinary" not in str(x).lower() for x in output["rationale"])


def test_invalid_action_is_rejected() -> None:
    frame = build_intervention_recommendations(pd.DataFrame([_row("P-1", "2026-01-01", "LOW", 0.1)]))
    frame.loc[0, "recommended_action"] = "BAD_ACTION"
    with pytest.raises(ValueError):
        validate_intervention_output(frame)


def test_deterministic_output() -> None:
    predictions = pd.DataFrame([
        _row("P-1", "2026-01-01", "MODERATE", 0.35),
        _row("P-1", "2026-01-02", "MODERATE", 0.36),
        _row("P-1", "2026-01-03", "HIGH", 0.58),
    ])
    a = build_intervention_recommendations(predictions)
    b = build_intervention_recommendations(predictions)
    pd.testing.assert_frame_equal(a, b)
