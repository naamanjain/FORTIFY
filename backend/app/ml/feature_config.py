"""Configurable Phase 2 feature-engineering assumptions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureConfig:
    """Operational simulation assumptions; not clinical thresholds."""

    short_rest_threshold_hours: float = 6.0
    recovery_target_hours: float = 8.0
    high_intensity_threshold: int = 4
    emergency_duty_types: tuple[str, ...] = ("EMERGENCY",)
    support_recent_window_days: int = 7
    min_history_for_std: int = 2
