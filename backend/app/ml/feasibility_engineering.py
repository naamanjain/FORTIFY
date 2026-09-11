from __future__ import annotations

from dataclasses import asdict
from typing import Any

import numpy as np
import pandas as pd

from .feasibility_config import FeasibilityPolicyConfig, VALID_ACTIONS, VALID_PRIORITIES, VALID_STATUSES

FORBIDDEN_TERMS = {
    "depression", "anxiety", "ptsd", "psychiatric", "mental illness", "medical diagnosis",
    "disciplinary", "punishment", "terminate employment", "performance rating", "termination",
}

REQUIRED_INTERVENTION_COLUMNS = {
    "person_id", "date", "risk_band", "recommended_action", "priority",
    "requires_human_review", "model_version", "policy_version",
}

OUTPUT_COLUMNS = [
    "person_id", "date", "risk_band", "recommended_action", "original_priority",
    "feasibility_status", "constraint_flags", "feasibility_rationale",
    "adjustment_recommendation", "requires_human_review", "model_version",
    "policy_version", "feasibility_policy_version",
]


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _active_interval_count(events: pd.DataFrame, person_id: str, date: pd.Timestamp, start_col: str, end_col: str) -> int:
    subset = events[events["person_id"].astype(str).eq(person_id)]
    if subset.empty:
        return 0
    return int(((subset[start_col] <= date) & (subset[end_col] >= date)).sum())


def _unit_pressure_lookup(duty: pd.DataFrame) -> pd.DataFrame:
    daily = duty.groupby(["unit_id", "date"], dropna=False)["duration_hours"].sum().reset_index(name="unit_day_duty_hours")
    pressure = daily.groupby("unit_id", dropna=False)["unit_day_duty_hours"].quantile(0.90).reset_index(name="unit_pressure_threshold")
    return daily.merge(pressure, on="unit_id", how="left", validate="many_to_one")


def _prepare_context(
    interventions: pd.DataFrame,
    personnel: pd.DataFrame,
    duty: pd.DataFrame,
    recovery: pd.DataFrame,
    leave: pd.DataFrame,
    deployment: pd.DataFrame,
    training: pd.DataFrame,
    config: FeasibilityPolicyConfig,
) -> pd.DataFrame:
    base = interventions.copy()
    base["person_id"] = base["person_id"].astype(str)
    base["date"] = pd.to_datetime(base["date"], errors="raise").dt.normalize()

    persons = personnel.copy()
    persons["person_id"] = persons["person_id"].astype(str)
    persons = persons[["person_id", "unit_id", "role", "deployment_type"]].drop_duplicates("person_id")
    base = base.merge(persons, on="person_id", how="left", validate="many_to_one")

    # Same-day duty context.
    duty = duty.copy()
    duty["person_id"] = duty["person_id"].astype(str)
    duty["date"] = pd.to_datetime(duty["date"], errors="raise").dt.normalize()
    duty["duration_hours"] = pd.to_numeric(duty["duration_hours"], errors="coerce").fillna(0.0)
    duty_with_unit = duty.merge(persons[["person_id", "unit_id"]], on="person_id", how="left", validate="many_to_one")
    duty_daily = duty_with_unit.groupby(["person_id", "unit_id", "date"], as_index=False).agg(
        duty_hours_1d=("duration_hours", "sum"),
        duty_events_1d=("duty_event_id", "count"),
    )
    duty_unit_daily = duty_with_unit.groupby(["unit_id", "date"], as_index=False)["duration_hours"].sum().rename(columns={"duration_hours": "unit_day_duty_hours"})
    if duty_unit_daily.empty:
        unit_threshold = pd.DataFrame(columns=["unit_id", "unit_pressure_threshold"])
    else:
        unit_threshold = duty_unit_daily.groupby("unit_id", dropna=False)["unit_day_duty_hours"].quantile(config.unit_pressure_quantile).rename("unit_pressure_threshold").reset_index()
    base = base.merge(duty_daily, on=["person_id", "unit_id", "date"], how="left", validate="one_to_one")
    base = base.merge(duty_unit_daily, on=["unit_id", "date"], how="left", validate="many_to_one")
    base = base.merge(unit_threshold, on="unit_id", how="left", validate="many_to_one")
    base["duty_hours_1d"] = pd.to_numeric(base["duty_hours_1d"], errors="coerce").infer_objects(copy=False).fillna(0.0)
    base["duty_events_1d"] = pd.to_numeric(base["duty_events_1d"], errors="coerce").fillna(0).astype(int)

    # Same-day recovery context.
    recovery = recovery.copy()
    recovery["person_id"] = recovery["person_id"].astype(str)
    recovery["date"] = pd.to_datetime(recovery["date"], errors="raise").dt.normalize()
    recovery["rest_duration_hours"] = pd.to_numeric(recovery["rest_duration_hours"], errors="coerce")
    recovery_daily = recovery.groupby(["person_id", "date"], as_index=False)["rest_duration_hours"].mean()
    base = base.merge(recovery_daily, on=["person_id", "date"], how="left", validate="one_to_one")

    # Same-day training context.
    training = training.copy()
    training["person_id"] = training["person_id"].astype(str)
    training["date"] = pd.to_datetime(training["date"], errors="raise").dt.normalize()
    training["duration_hours"] = pd.to_numeric(training["duration_hours"], errors="coerce").fillna(0.0)
    training_daily = training.groupby(["person_id", "date"], as_index=False)["duration_hours"].sum().rename(columns={"duration_hours": "training_hours_1d"})
    base = base.merge(training_daily, on=["person_id", "date"], how="left", validate="one_to_one")
    base["training_hours_1d"] = pd.to_numeric(base["training_hours_1d"], errors="coerce").fillna(0.0)

    # Expand interval events to day grain. Phase 1 intervals are small enough that this is
    # more efficient and less error-prone than 90k x event row-wise interval scans.
    leave2 = leave.copy()
    leave2["person_id"] = leave2["person_id"].astype(str)
    leave2["start_date"] = pd.to_datetime(leave2["start_date"], errors="raise").dt.normalize()
    leave2["end_date"] = pd.to_datetime(leave2["end_date"], errors="raise").dt.normalize()
    if leave2.empty:
        leave_daily = pd.DataFrame(columns=["person_id", "date", "active_leave_count"])
    else:
        leave_days = []
        for rec in leave2[["person_id", "start_date", "end_date"]].itertuples(index=False):
            leave_days.append(pd.DataFrame({"person_id": rec.person_id, "date": pd.date_range(rec.start_date, rec.end_date, freq="D")}))
        leave_daily = pd.concat(leave_days, ignore_index=True).groupby(["person_id", "date"], as_index=False).size().rename(columns={"size": "active_leave_count"})
    base = base.merge(leave_daily, on=["person_id", "date"], how="left", validate="one_to_one")
    base["active_leave_count"] = pd.to_numeric(base["active_leave_count"], errors="coerce").fillna(0).astype(int)

    dep = deployment.copy()
    dep["person_id"] = dep["person_id"].astype(str)
    dep["start_date"] = pd.to_datetime(dep["start_date"], errors="raise").dt.normalize()
    dep["end_date"] = pd.to_datetime(dep["end_date"], errors="raise").dt.normalize()
    dep["intensity_level"] = pd.to_numeric(dep["intensity_level"], errors="coerce")
    if dep.empty:
        dep_daily = pd.DataFrame(columns=["person_id", "date", "active_deployment_count", "deployment_intensity"])
    else:
        dep_days = []
        for rec in dep[["person_id", "start_date", "end_date", "intensity_level"]].itertuples(index=False):
            dep_days.append(pd.DataFrame({"person_id": rec.person_id, "date": pd.date_range(rec.start_date, rec.end_date, freq="D"), "deployment_intensity": rec.intensity_level}))
        dep_daily = pd.concat(dep_days, ignore_index=True).groupby(["person_id", "date"], as_index=False).agg(
            active_deployment_count=("deployment_intensity", "size"),
            deployment_intensity=("deployment_intensity", "max"),
        )
    base = base.merge(dep_daily, on=["person_id", "date"], how="left", validate="one_to_one")
    base["active_deployment_count"] = pd.to_numeric(base["active_deployment_count"], errors="coerce").fillna(0).astype(int)

    return base

def _flags(row: pd.Series, config: FeasibilityPolicyConfig) -> list[str]:
    flags: list[str] = []
    duty_hours = _safe_float(row.get("duty_hours_1d")) or 0.0
    rest = _safe_float(row.get("rest_duration_hours"))
    training_hours = _safe_float(row.get("training_hours_1d")) or 0.0
    unit_hours = _safe_float(row.get("unit_day_duty_hours"))
    unit_threshold = _safe_float(row.get("unit_pressure_threshold"))

    if duty_hours > 0:
        flags.append("active_duty_conflict")
    if duty_hours >= config.workload_hours_constrained:
        flags.append("excessive_recent_workload")
    if rest is not None and rest < config.recovery_hours_constrained:
        flags.append("insufficient_recovery_opportunity")
    if (_safe_float(row.get("active_deployment_count")) or 0) > 0:
        flags.append("active_deployment")
    if (_safe_float(row.get("active_leave_count")) or 0) > 0:
        flags.append("leave_conflict")
    if training_hours > 0:
        flags.append("training_conflict")
    if unit_hours is not None and unit_threshold is not None and unit_hours > unit_threshold:
        flags.append("unit_operational_pressure")
    return flags


def _decision(action: str, flags: list[str], row: pd.Series, config: FeasibilityPolicyConfig) -> tuple[str, str | None]:
    # No timing/resource conflict for routine monitoring or continuing existing support.
    if action in {"ROUTINE_MONITORING", "CONTINUE_EXISTING_SUPPORT"} and not flags:
        return "FEASIBLE", None

    hard = 0
    soft = 0
    duty = _safe_float(row.get("duty_hours_1d")) or 0.0
    rest = _safe_float(row.get("rest_duration_hours"))
    training = _safe_float(row.get("training_hours_1d")) or 0.0
    deployment = (_safe_float(row.get("active_deployment_count")) or 0) > 0
    leave = (_safe_float(row.get("active_leave_count")) or 0) > 0
    if leave and action in {"SUPERVISOR_WELFARE_REVIEW", "PRIORITY_WELFARE_REVIEW"}:
        hard += 1
    elif duty > 0 and action in config.adjustment_actions:
        soft += 1
    if duty >= config.workload_hours_not_feasible:
        hard += 1
    elif duty >= config.workload_hours_constrained:
        soft += 1
    if rest is not None and rest < config.recovery_hours_not_feasible:
        hard += 1
    elif rest is not None and rest < config.recovery_hours_constrained:
        soft += 1
    if deployment:
        soft += 1
    if training > 0:
        soft += 1
    if "unit_operational_pressure" in flags:
        soft += 1

    if hard >= config.not_feasible_conflict_count or hard >= 2:
        return "NOT_FEASIBLE", "Coordinate a different implementation window with the human welfare coordinator; the current timing contains multiple hard operational conflicts."
    if hard == 1 and soft >= 1:
        return "CONSTRAINED", "Human coordination is required because the current timing includes a hard operational conflict plus another active constraint."
    if soft >= 2:
        return "CONSTRAINED", "Human coordination is required because multiple operational constraints are active at the current timing."
    if soft == 1:
        return "FEASIBLE_WITH_ADJUSTMENT", "Consider rescheduling the support action to a lower-conflict duty, training, deployment, or recovery window."
    return "FEASIBLE", None


def _rationale(status: str, flags: list[str], adjustment: str | None) -> str:
    if not flags:
        return "No material operational constraint was identified from the available same-day data; the Phase 6 welfare-support recommendation is operationally feasible."
    readable = ", ".join(flags).replace("_", " ")
    if status == "FEASIBLE_WITH_ADJUSTMENT":
        return f"The recommendation is feasible with timing adjustment because these operational constraints are present: {readable}."
    if status == "CONSTRAINED":
        return f"The recommendation is operationally constrained by the following available signals: {readable}. Human coordination should review timing and implementation."
    if status == "NOT_FEASIBLE":
        return f"The recommendation is not feasible at the current timing because multiple operational conflicts are present: {readable}. Human coordination should select another implementation window."
    return f"The recommendation remains feasible despite the following minor operational signal(s): {readable}."


def build_intervention_feasibility(
    interventions: pd.DataFrame,
    personnel: pd.DataFrame,
    duty: pd.DataFrame,
    recovery: pd.DataFrame,
    leave: pd.DataFrame,
    deployment: pd.DataFrame,
    training: pd.DataFrame,
    *,
    config: FeasibilityPolicyConfig | None = None,
) -> pd.DataFrame:
    config = config or FeasibilityPolicyConfig()
    missing = sorted(REQUIRED_INTERVENTION_COLUMNS - set(interventions.columns))
    if missing:
        raise ValueError(f"Phase 6 input missing columns: {missing}")
    if not set(interventions["recommended_action"].astype(str)).issubset(VALID_ACTIONS):
        raise ValueError("Unknown Phase 6 recommendation action")

    ctx = _prepare_context(interventions, personnel, duty, recovery, leave, deployment, training, config)
    rows: list[dict[str, Any]] = []
    for record in ctx.sort_values(["person_id", "date"], kind="mergesort").itertuples(index=False):
        row = pd.Series(record._asdict())
        flags = _flags(row, config)
        status, adjustment = _decision(str(row["recommended_action"]), flags, row, config)
        requires_review = bool(row["requires_human_review"]) or status in {"CONSTRAINED", "NOT_FEASIBLE"}
        if status == "FEASIBLE_WITH_ADJUSTMENT":
            requires_review = True
        rows.append({
            "person_id": str(row["person_id"]),
            "date": pd.Timestamp(row["date"]).strftime("%Y-%m-%d"),
            "risk_band": str(row["risk_band"]),
            "recommended_action": str(row["recommended_action"]),
            "original_priority": str(row["priority"]),
            "feasibility_status": status,
            "constraint_flags": " | ".join(flags),
            "feasibility_rationale": _rationale(status, flags, adjustment),
            "adjustment_recommendation": adjustment,
            "requires_human_review": requires_review,
            "model_version": str(row["model_version"]),
            "policy_version": str(row["policy_version"]),
            "feasibility_policy_version": config.feasibility_policy_version,
        })
    output = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    validate_feasibility_output(output)
    return output


def validate_feasibility_output(frame: pd.DataFrame) -> None:
    missing = sorted(set(OUTPUT_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"Feasibility output missing columns: {missing}")
    if frame[["person_id", "date"]].duplicated().any():
        raise ValueError("Duplicate person/date records")
    if not set(frame["feasibility_status"].astype(str)).issubset(VALID_STATUSES):
        raise ValueError("Invalid feasibility status")
    if not set(frame["original_priority"].astype(str)).issubset(VALID_PRIORITIES):
        raise ValueError("Invalid priority")
    if not set(frame["recommended_action"].astype(str)).issubset(VALID_ACTIONS):
        raise ValueError("Invalid recommendation action")
    if frame["date"].isna().any():
        raise ValueError("Invalid dates")
    text = frame.astype(str).to_string(index=False).lower()
    for term in FORBIDDEN_TERMS:
        if term in text:
            raise ValueError(f"Forbidden safety terminology detected: {term}")
    for col in ["person_id", "date", "risk_band", "recommended_action", "original_priority", "feasibility_status", "constraint_flags", "feasibility_rationale", "adjustment_recommendation", "requires_human_review", "model_version", "policy_version", "feasibility_policy_version"]:
        if col not in frame.columns:
            raise ValueError(col)


def config_dict(config: FeasibilityPolicyConfig) -> dict[str, Any]:
    values = asdict(config)
    values["adjustment_actions"] = sorted(config.adjustment_actions)
    return values
