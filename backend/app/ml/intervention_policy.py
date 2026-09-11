from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .intervention_config import InterventionPolicyConfig

VALID_RISK_BANDS = {"LOW", "MODERATE", "HIGH"}
VALID_PRIORITIES = {"LOW", "MEDIUM", "HIGH"}
FORBIDDEN_TERMS = {
    "depression",
    "anxiety",
    "ptsd",
    "psychiatric",
    "mental illness",
    "medical diagnosis",
    "disciplinary",
    "punishment",
    "terminate employment",
}


def _present(value: Any) -> bool:
    return value is not None and not (isinstance(value, float) and np.isnan(value)) and pd.notna(value)


def _has_positive(row: pd.Series, *columns: str) -> bool:
    for column in columns:
        value = row.get(column)
        if _present(value):
            try:
                if float(value) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _has_reduced_recovery(row: pd.Series, reference: float) -> bool:
    value = row.get("avg_rest_7d")
    if not _present(value):
        return False
    try:
        return float(value) < reference
    except (TypeError, ValueError):
        return False


def _context_signals(row: pd.Series, config: InterventionPolicyConfig) -> list[str]:
    signals: list[str] = []
    if _present(row.get("contributing_operational_signals")):
        raw = str(row["contributing_operational_signals"])
        if raw and raw.lower() != "nan":
            signals.extend([item.strip() for item in raw.split(" | ") if item.strip()])

    if _has_positive(row, "duty_hours_7d_personal_deviation", "duty_hours_30d_personal_deviation"):
        signals.append("current workload is elevated relative to personal history")
    if _has_positive(row, "night_shifts_30d_personal_deviation"):
        signals.append("night-shift exposure is elevated relative to personal history")
    if _has_reduced_recovery(row, config.recovery_hours_reference):
        signals.append("recent recovery is below the configured operational reference")
    if _has_positive(row, "incident_count_30d_personal_deviation"):
        signals.append("recent incident exposure is elevated relative to personal history")
    if _has_positive(row, "duty_hours_30d_cohort_relative_deviation", "duty_hours_30d_operational_relative_deviation"):
        signals.append("workload is elevated relative to available cohort or operational context")
    if _has_positive(row, "deployment_days_30d"):
        signals.append("recent deployment exposure is present")

    # Stable deterministic deduplication.
    return list(dict.fromkeys(signals))


def _choose_action(row: pd.Series, config: InterventionPolicyConfig) -> tuple[str, str, bool]:
    band = str(row["risk_band"])
    signals = _context_signals(row, config)

    if band == "LOW":
        return config.low_action, config.low_priority, config.low_requires_human_review

    if band == "HIGH":
        return config.high_action, config.high_priority, config.high_requires_human_review

    # MODERATE: use operational context to distinguish a recovery-focused action
    # from a general welfare check-in. Supervisor review is used when multiple
    # operational/context signals are present and the case therefore warrants
    # human attention beyond routine check-in.
    recovery_signal = _has_reduced_recovery(row, config.recovery_hours_reference)
    workload_signal = _has_positive(
        row,
        "duty_hours_7d_personal_deviation",
        "duty_hours_30d_personal_deviation",
        "duty_hours_30d_cohort_relative_deviation",
        "duty_hours_30d_operational_relative_deviation",
    )
    incident_signal = _has_positive(row, "incident_count_30d_personal_deviation")

    if recovery_signal:
        return config.moderate_recovery_action, config.moderate_priority, config.moderate_requires_human_review
    if workload_signal or incident_signal or len(signals) >= 2:
        return config.moderate_supervisor_action, config.moderate_priority, config.moderate_requires_human_review
    return config.moderate_checkin_action, config.moderate_priority, config.moderate_requires_human_review


def _risk_rank(band: str) -> int:
    return {"LOW": 0, "MODERATE": 1, "HIGH": 2}[band]


def _materially_increased(current: pd.Series, previous: pd.Series, config: InterventionPolicyConfig) -> bool:
    current_band = str(current["risk_band"])
    previous_band = str(previous["risk_band"])
    if _risk_rank(current_band) > _risk_rank(previous_band):
        return True
    try:
        return float(current["welfare_risk_probability"]) - float(previous["welfare_risk_probability"]) >= config.material_probability_increase
    except (TypeError, ValueError):
        return False


def build_intervention_recommendations(
    phase5_decisions: pd.DataFrame,
    feature_frame: pd.DataFrame | None = None,
    *,
    config: InterventionPolicyConfig | None = None,
) -> pd.DataFrame:
    """Build one deterministic welfare-support recommendation per person-day."""
    config = config or InterventionPolicyConfig()
    required = {"person_id", "date", "welfare_risk_probability", "risk_band", "threshold_decision", "model_version"}
    missing = sorted(required.difference(phase5_decisions.columns))
    if missing:
        raise ValueError(f"Phase 5 input missing columns: {missing}")

    decisions = phase5_decisions.copy()
    decisions["person_id"] = decisions["person_id"].astype(str)
    decisions["date"] = pd.to_datetime(decisions["date"], errors="raise").dt.normalize()
    decisions = decisions.sort_values(["person_id", "date"], kind="mergesort").reset_index(drop=True)

    context_columns = [
        "person_id", "date", "avg_rest_7d", "duty_hours_7d_personal_deviation",
        "duty_hours_30d_personal_deviation", "night_shifts_30d_personal_deviation",
        "duty_hours_30d_cohort_relative_deviation", "duty_hours_30d_operational_relative_deviation",
        "incident_count_30d_personal_deviation", "deployment_days_30d",
        "contributing_operational_signals",
    ]
    if feature_frame is not None:
        missing_context_keys = {"person_id", "date"}.difference(feature_frame.columns)
        if missing_context_keys:
            raise ValueError(f"feature_frame missing required keys: {sorted(missing_context_keys)}")
        available = [column for column in context_columns if column in feature_frame.columns]
        context = feature_frame[available].copy()
        context["person_id"] = context["person_id"].astype(str)
        context["date"] = pd.to_datetime(context["date"], errors="raise").dt.normalize()
        if context[["person_id", "date"]].duplicated().any():
            raise ValueError("feature_frame contains duplicate person/date keys")
        decisions = decisions.merge(context, on=["person_id", "date"], how="left", validate="one_to_one", sort=False)

    rows: list[dict[str, Any]] = []
    for record in decisions.itertuples(index=False):
        row = pd.Series(record._asdict())
        recommended_action, priority, requires_human_review = _choose_action(row, config)
        rationale_signals = _context_signals(row, config)
        band = str(row["risk_band"])
        rationale_map = {
            "LOW": "The current welfare-monitoring signal is low; routine monitoring is appropriate.",
            "MODERATE": "The current welfare-monitoring signal is moderate; a welfare-support action is appropriate based on available operational context.",
            "HIGH": "The current welfare-monitoring signal is high; priority human welfare review is appropriate.",
        }
        rationale = rationale_map[band]
        if rationale_signals:
            rationale += " " + "Signals supporting the recommendation: " + "; ".join(rationale_signals[:3]) + "."

        rows.append({
            "person_id": str(row["person_id"]),
            "date": pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
            "risk_band": band,
            "welfare_risk_probability": float(row["welfare_risk_probability"]),
            "threshold_decision": str(row["threshold_decision"]),
            "recommended_action": recommended_action,
            "priority": priority,
            "rationale": rationale,
            "contributing_signals": " | ".join(rationale_signals[:3]) if rationale_signals else None,
            "requires_human_review": bool(requires_human_review),
            "safety_note": "Welfare-support recommendation only; human oversight is required and no medical or punitive conclusion is implied.",
            "model_version": str(row["model_version"]),
            "policy_version": config.policy_version,
        })

    output = pd.DataFrame(rows)
    output = _apply_cooldown(output, config)
    validate_intervention_output(output)
    return output


def _apply_cooldown(output: pd.DataFrame, config: InterventionPolicyConfig) -> pd.DataFrame:
    """Suppress repeated consecutive recommendations without row-by-row mutation."""
    result = output.copy()
    result["_base_action"] = result["recommended_action"]
    result["_previous_action"] = result.groupby("person_id", sort=False)["_base_action"].shift(1)
    result["_previous_probability"] = result.groupby("person_id", sort=False)["welfare_risk_probability"].shift(1)
    result["_previous_band"] = result.groupby("person_id", sort=False)["risk_band"].shift(1)
    result["_previous_date"] = result.groupby("person_id", sort=False)["date"].shift(1)

    current_date = pd.to_datetime(result["date"], errors="raise")
    previous_date = pd.to_datetime(result["_previous_date"], errors="coerce")
    consecutive_day = (current_date - previous_date).dt.days.eq(1)
    same_action = result["_base_action"].eq(result["_previous_action"])
    previous_band_rank = result["_previous_band"].map({"LOW": 0, "MODERATE": 1, "HIGH": 2})
    current_band_rank = result["risk_band"].map({"LOW": 0, "MODERATE": 1, "HIGH": 2})
    band_increased = current_band_rank.gt(previous_band_rank)
    probability_increased = (result["welfare_risk_probability"] - result["_previous_probability"]) >= config.material_probability_increase
    materially_increased = band_increased | probability_increased

    # cooldown_consecutive_days=N means suppress after N repeated prior consecutive days.
    # Current policy default is N=1. A run-length calculation keeps the behavior deterministic.
    run_break = (~consecutive_day) | (~same_action) | materially_increased
    run_id = run_break.groupby(result["person_id"], sort=False).cumsum()
    repeat_number = result.groupby(["person_id", run_id], sort=False).cumcount()
    suppress = same_action & consecutive_day & (~materially_increased) & (repeat_number >= config.cooldown_consecutive_days)

    result.loc[suppress, "recommended_action"] = config.continue_action
    result.loc[suppress, "rationale"] = "Continue existing welfare support; no material change in the monitored signal requires a new action today."

    result = result.drop(columns=[
        "_base_action", "_previous_action", "_previous_probability", "_previous_band", "_previous_date"
    ])
    return result


def validate_intervention_output(output: pd.DataFrame) -> None:
    required = {
        "person_id", "date", "risk_band", "welfare_risk_probability", "threshold_decision",
        "recommended_action", "priority", "rationale", "contributing_signals",
        "requires_human_review", "safety_note", "model_version", "policy_version",
    }
    missing = sorted(required.difference(output.columns))
    if missing:
        raise ValueError(f"Intervention output missing required columns: {missing}")
    if output[["person_id", "date"]].duplicated().any():
        raise ValueError("Duplicate person/date recommendation rows found")
    if not set(output["risk_band"].dropna().unique()).issubset(VALID_RISK_BANDS):
        raise ValueError("Invalid risk band present")
    if not set(output["priority"].dropna().unique()).issubset(VALID_PRIORITIES):
        raise ValueError("Invalid priority present")
    actions = set(output["recommended_action"].dropna().unique())
    allowed_actions = {
        "ROUTINE_MONITORING", "WELLNESS_CHECK_IN", "RECOVERY_SUPPORT", "SUPERVISOR_WELFARE_REVIEW",
        "PRIORITY_WELFARE_REVIEW", "HUMAN_ESCALATION_RECOMMENDED", "CONTINUE_EXISTING_SUPPORT",
    }
    if not actions.issubset(allowed_actions):
        raise ValueError(f"Invalid intervention category present: {sorted(actions - allowed_actions)}")
    if not output["requires_human_review"].isin([True, False]).all():
        raise ValueError("requires_human_review must be boolean")
    searchable = " ".join(output["rationale"].astype(str).tolist() + output["safety_note"].astype(str).tolist()).lower()
    forbidden = sorted(term for term in FORBIDDEN_TERMS if term in searchable)
    if forbidden:
        raise ValueError(f"Forbidden safety terminology present: {forbidden}")
    if "perceived_stress" in " ".join(output.columns).lower():
        raise ValueError("Raw wellness target fields must not be present in intervention output")


def config_dict(config: InterventionPolicyConfig) -> dict[str, Any]:
    return asdict(config)
