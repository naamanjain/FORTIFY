from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple

FORBIDDEN_INPUT_COLUMNS = {
    "stress_label",
    "stress_score",
    "mental_health_label",
    "depression_label",
    "anxiety_label",
    "risk_score",
    "risk_band",
}

# Wellness-derived fields are intentionally excluded from model inputs. They remain
# available for future observed-label construction and later analysis, but sparse
# voluntary reporting must not become an implicit predictive signal.
WELLNESS_INPUT_PATTERNS: Tuple[str, ...] = (
    "mood_",
    "energy_",
    "sleep_quality_",
    "perceived_stress_",
    "workload_manageability_",
    "support_request",
    "wellness_",
)

DEFAULT_TARGET_NAME = "future_high_perceived_stress_7d"
DEFAULT_TARGET_HORIZON_DAYS = 7
DEFAULT_TARGET_THRESHOLD = 4

@dataclass(frozen=True)
class ModelConfig:
    target_name: str = DEFAULT_TARGET_NAME
    target_horizon_days: int = DEFAULT_TARGET_HORIZON_DAYS
    target_threshold: int = DEFAULT_TARGET_THRESHOLD
    train_fraction: float = 0.60
    validation_fraction: float = 0.20
    test_fraction: float = 0.20
    random_state: int = 42
    min_training_samples: int = 100
    max_iter: int = 1000
    class_weight: str | None = "balanced"
    risk_thresholds: tuple[float, float] = field(default_factory=lambda: (0.33, 0.66))

    def __post_init__(self) -> None:
        if self.target_horizon_days < 1:
            raise ValueError("target_horizon_days must be >= 1")
        if not 1 <= self.target_threshold <= 5:
            raise ValueError("target_threshold must be between 1 and 5")
        if abs(self.train_fraction + self.validation_fraction + self.test_fraction - 1.0) > 1e-9:
            raise ValueError("train/validation/test fractions must sum to 1")
        if self.min_training_samples < 1:
            raise ValueError("min_training_samples must be >= 1")
        if len(self.risk_thresholds) != 2 or not 0 <= self.risk_thresholds[0] < self.risk_thresholds[1] <= 1:
            raise ValueError("risk_thresholds must contain two ordered probabilities in [0, 1]")
