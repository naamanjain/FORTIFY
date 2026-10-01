"""Tests for the deterministic alert policy (score → signal → case).

The alert policy is the layer between the model and the human. These tests pin
every rule: the evidence gate, persistence, duplicate suppression, escalation,
recovery, and the daily budget — including the requirement that budget
suppression is *recorded*, never silent.
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.ml.alert_policy import (
    ALERT_STATES,
    AlertPolicyConfig,
    evaluate_alert_policy,
)


def decisions(scores_by_day: dict[str, list[tuple[str, float, str]]]) -> pd.DataFrame:
    rows = []
    for person_id, series in scores_by_day.items():
        for day, (date, score, band) in enumerate(series):
            rows.append({"person_id": person_id,
                         "date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=day),
                         "date_actual": date,
                         "welfare_risk_probability": score,
                         "risk_band": band})
    # Use the supplied date strings rather than synthetic consecutive days when
    # given explicit dates.
    frame = pd.DataFrame(rows)
    if all(isinstance(d, str) for d in frame["date_actual"]):
        frame["date"] = pd.to_datetime(frame["date_actual"])
    return frame.drop(columns=["date_actual"])


def test_persistence_gate_requires_consecutive_days() -> None:
    """One gate-passing day must NOT open a case; two consecutive days must."""
    # Scores sit above the 0.40 gate but below gate+escalation_jump, so this
    # isolates the persistence rule from the sudden-deterioration rule.
    frame = decisions({"P-1": [("2026-01-01", 0.45, "HIGH"), ("2026-01-02", 0.47, "HIGH")]})
    queue = evaluate_alert_policy(frame, AlertPolicyConfig(persistence_days=2))
    day1 = queue[queue["date"] == "2026-01-01"]
    day2 = queue[queue["date"] == "2026-01-02"]
    assert not day1["case_created"].any(), "a single gate day opened a case"
    assert day2["case_created"].any(), "two consecutive gate days failed to open a case"
    assert set(day2["alert_state"]) == {"NEW_ALERT"}


def test_sudden_deterioration_opens_immediately() -> None:
    """A jump of escalation_jump above the gate opens on day one."""
    config = AlertPolicyConfig(persistence_days=3, minimum_score=0.40, escalation_jump=0.15)
    frame = decisions({"P-1": [("2026-01-01", 0.75, "HIGH")]})
    queue = evaluate_alert_policy(frame, config)
    assert queue["case_created"].any(), "sudden deterioration did not open a case immediately"


def test_below_gate_never_creates_a_case() -> None:
    frame = decisions({"P-1": [(f"2026-01-{d:02d}", 0.20, "LOW") for d in range(1, 10)]})
    queue = evaluate_alert_policy(frame, AlertPolicyConfig())
    assert not queue["case_created"].any()
    assert set(queue["alert_state"]) == {"BELOW_GATE"}


def test_open_case_suppresses_duplicate_daily_cases() -> None:
    """The core alert-fatigue rule: one sustained case, not one per day."""
    config = AlertPolicyConfig(persistence_days=1)
    frame = decisions({"P-1": [(f"2026-01-{d:02d}", 0.70, "HIGH") for d in range(1, 11)]})
    queue = evaluate_alert_policy(frame, config)
    created = queue[queue["case_created"]]
    assert len(created) == 1, f"open case produced {len(created)} cases over 10 days"
    persisted = queue[queue["alert_state"] == "PERSISTENT"]
    assert len(persisted) == 9


def test_escalation_on_open_case() -> None:
    config = AlertPolicyConfig(persistence_days=1, escalation_jump=0.15)
    frame = decisions({"P-1": [("2026-01-01", 0.60, "MODERATE"),
                               ("2026-01-02", 0.62, "MODERATE"),
                               ("2026-01-03", 0.80, "HIGH")]})
    queue = evaluate_alert_policy(frame, config)
    escalated = queue[queue["alert_state"] == "ESCALATED"]
    assert len(escalated) == 1
    assert escalated.iloc[0]["date"] == pd.Timestamp("2026-01-03")
    # Escalation never creates a second case.
    assert len(queue[queue["case_created"]]) == 1


def test_recovery_state_after_sustained_easing() -> None:
    config = AlertPolicyConfig(persistence_days=1, recovery_score=0.30, recovery_days=3)
    frame = decisions({"P-1": [
        ("2026-01-01", 0.65, "HIGH"),
        ("2026-01-02", 0.25, "LOW"), ("2026-01-03", 0.22, "LOW"), ("2026-01-04", 0.20, "LOW"),
    ]})
    queue = evaluate_alert_policy(frame, config)
    recovered = queue[queue["alert_state"] == "RECOVERED"]
    assert len(recovered) == 1
    # Recovery marks the signal, and does NOT auto-close the case.
    assert not queue["case_closed"].any() if "case_closed" in queue else True


def test_observation_gap_restarts_persistence() -> None:
    """Missing days are not continued evidence."""
    config = AlertPolicyConfig(persistence_days=2)
    frame = decisions({"P-1": [("2026-01-01", 0.45, "HIGH"),
                               ("2026-01-05", 0.45, "HIGH")]})
    queue = evaluate_alert_policy(frame, config)
    # The gap restarts the run, so no day reaches persistence 2.
    assert not queue["case_created"].any()


def test_daily_budget_suppresses_overflow_and_records_it() -> None:
    """Over-budget candidates must be visible as SUPPRESSED_BUDGET, not dropped."""
    config = AlertPolicyConfig(persistence_days=1, max_daily_review_cases=2)
    frame = decisions({
        f"P-{i}": [("2026-01-01", 0.60 + i * 0.01, "HIGH")] for i in range(1, 6)
    })
    queue = evaluate_alert_policy(frame, config)
    created = queue[queue["case_created"]]
    suppressed = queue[queue["alert_state"] == "SUPPRESSED_BUDGET"]
    assert len(created) == 2
    assert len(suppressed) == 3
    # The highest scores win the budget.
    assert set(created["person_id"]) == {"P-5", "P-4"}
    assert suppressed["suppressed_by_budget"].all()
    assert suppressed["reason"].str.contains("budget").all()


def test_band_gate_blocks_low_band_even_with_score() -> None:
    """A passing score in a LOW band does not meet the evidence gate."""
    config = AlertPolicyConfig(minimum_score=0.40, minimum_band="MODERATE")
    frame = decisions({"P-1": [("2026-01-01", 0.50, "LOW"), ("2026-01-02", 0.50, "LOW")]})
    queue = evaluate_alert_policy(frame, config)
    assert not queue["case_created"].any()


def test_config_validation() -> None:
    with pytest.raises(ValueError):
        AlertPolicyConfig(recovery_score=0.9, minimum_score=0.4)
    with pytest.raises(ValueError):
        AlertPolicyConfig(persistence_days=0)
    with pytest.raises(ValueError):
        AlertPolicyConfig(minimum_band="CRITICAL")


def test_states_are_from_vocabulary() -> None:
    frame = decisions({"P-1": [("2026-01-01", 0.70, "HIGH"), ("2026-01-02", 0.71, "HIGH"),
                               ("2026-01-03", 0.20, "LOW"), ("2026-01-04", 0.21, "LOW")]})
    queue = evaluate_alert_policy(frame, AlertPolicyConfig(persistence_days=1, recovery_days=2))
    assert set(queue["alert_state"]).issubset(set(ALERT_STATES))


def test_empty_input() -> None:
    queue = evaluate_alert_policy(pd.DataFrame(columns=[
        "person_id", "date", "welfare_risk_probability", "risk_band"]))
    assert queue.empty
