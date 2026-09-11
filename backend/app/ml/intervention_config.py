from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InterventionPolicyConfig:
    """Central configuration for deterministic Phase 6 welfare-support policy."""

    policy_version: str = "phase6-v1"
    cooldown_consecutive_days: int = 1
    material_probability_increase: float = 0.10
    recovery_hours_reference: float = 8.0

    low_action: str = "ROUTINE_MONITORING"
    moderate_recovery_action: str = "RECOVERY_SUPPORT"
    moderate_checkin_action: str = "WELLNESS_CHECK_IN"
    moderate_supervisor_action: str = "SUPERVISOR_WELFARE_REVIEW"
    high_action: str = "PRIORITY_WELFARE_REVIEW"

    low_priority: str = "LOW"
    moderate_priority: str = "MEDIUM"
    high_priority: str = "HIGH"

    low_requires_human_review: bool = False
    moderate_requires_human_review: bool = True
    high_requires_human_review: bool = True

    continue_action: str = "CONTINUE_EXISTING_SUPPORT"

    def __post_init__(self) -> None:
        if self.cooldown_consecutive_days < 1:
            raise ValueError("cooldown_consecutive_days must be >= 1")
        if not 0 < self.material_probability_increase <= 1:
            raise ValueError("material_probability_increase must be in (0, 1]")
        if self.recovery_hours_reference <= 0:
            raise ValueError("recovery_hours_reference must be positive")
