from __future__ import annotations

from dataclasses import dataclass, field

VALID_STATUSES = {"FEASIBLE", "FEASIBLE_WITH_ADJUSTMENT", "CONSTRAINED", "NOT_FEASIBLE"}
VALID_PRIORITIES = {"LOW", "MEDIUM", "HIGH"}
VALID_ACTIONS = {
    "ROUTINE_MONITORING",
    "WELLNESS_CHECK_IN",
    "RECOVERY_SUPPORT",
    "SUPERVISOR_WELFARE_REVIEW",
    "PRIORITY_WELFARE_REVIEW",
    "CONTINUE_EXISTING_SUPPORT",
}


@dataclass(frozen=True)
class FeasibilityPolicyConfig:
    """Centralized, deterministic Phase 7 feasibility assumptions."""

    feasibility_policy_version: str = "phase7-v1"
    workload_hours_constrained: float = 10.0
    workload_hours_not_feasible: float = 14.0
    recovery_hours_constrained: float = 6.0
    recovery_hours_not_feasible: float = 4.0
    deployment_intensity_constrained: int = 4
    unit_pressure_quantile: float = 0.90
    not_feasible_conflict_count: int = 3
    adjustment_actions: frozenset[str] = field(
        default_factory=lambda: frozenset({"WELLNESS_CHECK_IN", "RECOVERY_SUPPORT", "SUPERVISOR_WELFARE_REVIEW", "PRIORITY_WELFARE_REVIEW"})
    )

    def __post_init__(self) -> None:
        if self.workload_hours_not_feasible <= self.workload_hours_constrained:
            raise ValueError("workload_hours_not_feasible must exceed constrained threshold")
        if self.recovery_hours_not_feasible >= self.recovery_hours_constrained:
            raise ValueError("recovery_hours_not_feasible must be below constrained threshold")
        if not 0 < self.unit_pressure_quantile < 1:
            raise ValueError("unit_pressure_quantile must be in (0, 1)")
        if self.not_feasible_conflict_count < 1:
            raise ValueError("not_feasible_conflict_count must be >= 1")
