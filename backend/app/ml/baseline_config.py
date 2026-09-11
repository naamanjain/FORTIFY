from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class BaselineConfig:
    """Configurable assumptions for Phase 3 contextual baselines."""

    minimum_personal_history_days: int = 14
    minimum_cohort_size: int = 10
    minimum_operational_size: int = 10
    near_zero_denominator: float = 1e-9
    feature_metrics: Tuple[str, ...] = field(
        default=(
            "duty_hours_7d",
            "duty_hours_30d",
            "night_shifts_30d",
            "duty_density_30d",
            "avg_rest_7d",
            "min_rest_7d",
            "training_hours_30d",
            "incident_count_30d",
        )
    )
