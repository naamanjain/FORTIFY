from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, precision_score, recall_score, roc_auc_score


FORBIDDEN_OUTPUT_COLUMNS = {
    "mood_latest",
    "mood_7d_mean",
    "mood_30d_mean",
    "energy_latest",
    "energy_7d_mean",
    "energy_30d_mean",
    "sleep_quality_latest",
    "sleep_quality_7d_mean",
    "sleep_quality_30d_mean",
    "perceived_stress_latest",
    "perceived_stress_7d_mean",
    "perceived_stress_30d_mean",
    "workload_manageability_latest",
    "workload_manageability_7d_mean",
    "support_request_recent",
}


@dataclass(frozen=True)
class DecisionConfig:
    decision_threshold_candidates: tuple[float, ...] = (
        0.10,
        0.15,
        0.20,
        0.25,
        0.30,
        0.35,
        0.40,
        0.45,
        0.50,
        0.55,
        0.60,
    )
    minimum_validation_recall: float = 0.80
    low_band_upper: float = 0.25
    moderate_band_upper: float = 0.50
    calibration_bins: int = 10
    random_state: int = 42

    def __post_init__(self) -> None:
        candidates = tuple(float(x) for x in self.decision_threshold_candidates)
        if not candidates or any(x <= 0 or x >= 1 for x in candidates):
            raise ValueError("decision thresholds must be strictly inside (0, 1)")
        if tuple(sorted(set(candidates))) != candidates:
            raise ValueError("decision thresholds must be strictly increasing")
        if not 0 < self.minimum_validation_recall <= 1:
            raise ValueError("minimum_validation_recall must be in (0, 1]")
        if not 0 < self.low_band_upper < self.moderate_band_upper < 1:
            raise ValueError("risk-band cutoffs must satisfy 0 < low < moderate < 1")
        if self.calibration_bins < 2:
            raise ValueError("calibration_bins must be >= 2")


@dataclass(frozen=True)
class ThresholdSelection:
    selected_threshold: float
    rule: str
    minimum_validation_recall: float


def threshold_metrics(y_true: Iterable[int], probabilities: Iterable[float], threshold: float) -> dict[str, Any]:
    y = np.asarray(list(y_true), dtype=int)
    p = np.asarray(list(probabilities), dtype=float)
    if len(y) != len(p):
        raise ValueError("y_true and probabilities must have equal length")
    if len(y) == 0:
        raise ValueError("threshold metrics require at least one sample")
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be in [0, 1]")

    pred = p >= threshold
    tp = int(np.sum((pred == 1) & (y == 1)))
    tn = int(np.sum((pred == 0) & (y == 0)))
    fp = int(np.sum((pred == 1) & (y == 0)))
    fn = int(np.sum((pred == 0) & (y == 1)))

    precision = precision_score(y, pred, zero_division=0)
    recall = recall_score(y, pred, zero_division=0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    specificity = tn / (tn + fp) if tn + fp else 0.0
    false_positive_rate = fp / (fp + tn) if fp + tn else 0.0
    false_negative_rate = fn / (fn + tp) if fn + tp else 0.0

    return {
        "threshold": float(threshold),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "specificity": float(specificity),
        "false_positive_rate": float(false_positive_rate),
        "false_negative_rate": float(false_negative_rate),
        "predicted_positive_count": int(pred.sum()),
        "predicted_positive_rate": float(pred.mean()),
        "true_positive": tp,
        "true_negative": tn,
        "false_positive": fp,
        "false_negative": fn,
    }


def analyze_thresholds(
    y_true: Iterable[int],
    probabilities: Iterable[float],
    thresholds: Iterable[float],
) -> pd.DataFrame:
    rows = [threshold_metrics(y_true, probabilities, float(t)) for t in thresholds]
    return pd.DataFrame(rows).sort_values("threshold").reset_index(drop=True)


def select_operating_threshold(
    threshold_table: pd.DataFrame,
    *,
    minimum_validation_recall: float = 0.80,
) -> ThresholdSelection:
    required = {"threshold", "recall", "f1", "precision"}
    missing = sorted(required.difference(threshold_table.columns))
    if missing:
        raise ValueError(f"Threshold table missing columns: {missing}")
    eligible = threshold_table[threshold_table["recall"] >= minimum_validation_recall].copy()
    if eligible.empty:
        raise ValueError("No candidate threshold satisfies the configured recall floor")
    eligible = eligible.sort_values(
        ["f1", "precision", "threshold"], ascending=[False, False, True], kind="mergesort"
    )
    chosen = float(eligible.iloc[0]["threshold"])
    return ThresholdSelection(
        selected_threshold=chosen,
        rule=(
            "Select the candidate threshold with the highest validation F1 among thresholds "
            "meeting the configured validation recall floor; break ties using precision, then lower threshold."
        ),
        minimum_validation_recall=float(minimum_validation_recall),
    )


def fit_platt_calibrator(validation_probabilities: Iterable[float], validation_targets: Iterable[int], random_state: int = 42) -> LogisticRegression:
    p = np.asarray(list(validation_probabilities), dtype=float)
    y = np.asarray(list(validation_targets), dtype=int)
    if len(p) != len(y) or len(p) == 0:
        raise ValueError("Calibration inputs must be non-empty and aligned")
    if np.unique(y).size < 2:
        raise ValueError("Calibration requires both classes")
    calibrator = LogisticRegression(max_iter=1000, solver="lbfgs", random_state=random_state)
    calibrator.fit(p.reshape(-1, 1), y)
    return calibrator


def apply_calibrator(calibrator: LogisticRegression, probabilities: Iterable[float]) -> np.ndarray:
    p = np.asarray(list(probabilities), dtype=float)
    return calibrator.predict_proba(p.reshape(-1, 1))[:, 1]


def calibration_diagnostics(y_true: Iterable[int], probabilities: Iterable[float], bins: int = 10) -> dict[str, Any]:
    y = np.asarray(list(y_true), dtype=int)
    p = np.asarray(list(probabilities), dtype=float)
    if len(y) != len(p) or len(y) == 0:
        raise ValueError("Calibration inputs must be non-empty and aligned")
    edges = np.linspace(0.0, 1.0, bins + 1)
    reliability = []
    abs_errors = []
    for idx in range(bins):
        left, right = edges[idx], edges[idx + 1]
        mask = (p >= left) & (p < right if idx < bins - 1 else p <= right)
        count = int(mask.sum())
        if count == 0:
            continue
        mean_probability = float(p[mask].mean())
        observed_rate = float(y[mask].mean())
        gap = abs(mean_probability - observed_rate)
        abs_errors.append(gap * count)
        reliability.append(
            {
                "bin": idx,
                "lower": float(left),
                "upper": float(right),
                "count": count,
                "mean_predicted_probability": mean_probability,
                "observed_positive_rate": observed_rate,
                "absolute_gap": float(gap),
            }
        )
    ece = float(sum(abs_errors) / len(y)) if len(y) else 0.0
    return {
        "brier_score": float(brier_score_loss(y, p)),
        "roc_auc": float(roc_auc_score(y, p)) if np.unique(y).size == 2 else None,
        "average_precision": float(average_precision_score(y, p)) if np.unique(y).size == 2 else None,
        "expected_calibration_error": ece,
        "bins": reliability,
    }


def assign_risk_band(probabilities: Iterable[float], config: DecisionConfig) -> np.ndarray:
    p = np.asarray(list(probabilities), dtype=float)
    return np.where(
        p < config.low_band_upper,
        "LOW",
        np.where(p < config.moderate_band_upper, "MODERATE", "HIGH"),
    )


def decision_signal(probabilities: Iterable[float], threshold: float) -> np.ndarray:
    p = np.asarray(list(probabilities), dtype=float)
    return np.where(p >= threshold, "EARLY_WARNING", "NO_EARLY_WARNING")


_OPERATIONAL_SIGNAL_DEFS = {
    "duty_hours_7d": ("elevated recent duty hours", "higher than the available personal 30-day duty reference", "duty_hours_7d_personal_deviation"),
    "night_shifts_30d": ("increased night-shift exposure", "higher than the available personal 30-day night-shift reference", "night_shifts_30d_personal_deviation"),
    "avg_rest_7d": ("reduced recent recovery", "lower than the configured 8-hour operational recovery reference", None),
    "duty_density_30d": ("higher duty density", "above the available personal 30-day duty-density reference", "duty_density_30d_personal_deviation"),
    "incident_count_30d": ("recent incident exposure", "above the available personal 30-day incident reference", "incident_count_30d_personal_deviation"),
    "deployment_days_30d": ("sustained deployment exposure", "present within the recent operational window", None),
    "duty_hours_30d_cohort_relative_deviation": ("duty load above the cohort reference", "above the same-day cohort reference", None),
    "duty_hours_30d_operational_relative_deviation": ("duty load above the operational reference", "above the same-day operational reference", None),
}


def _finite_positive(value: Any) -> bool:
    try:
        return bool(np.isfinite(float(value)) and float(value) > 0)
    except (TypeError, ValueError):
        return False


def generate_explanations(row: pd.Series, max_items: int = 3) -> list[str]:
    """Return non-clinical operational signals associated with a prediction.

    This routine never reads raw wellness-response columns.
    """
    candidates: list[tuple[float, str]] = []

    if _finite_positive(row.get("duty_hours_7d_personal_deviation")):
        value = float(row["duty_hours_7d_personal_deviation"])
        candidates.append((abs(value), f"{_OPERATIONAL_SIGNAL_DEFS['duty_hours_7d'][0]} ({value:+.1f} hours vs personal reference)"))
    if _finite_positive(row.get("night_shifts_30d_personal_deviation")):
        value = float(row["night_shifts_30d_personal_deviation"])
        candidates.append((abs(value), f"{_OPERATIONAL_SIGNAL_DEFS['night_shifts_30d'][0]} ({value:+.1f} shifts vs personal reference)"))
    avg_rest = row.get("avg_rest_7d")
    if avg_rest is not None and pd.notna(avg_rest) and float(avg_rest) < 8.0:
        candidates.append((8.0 - float(avg_rest), f"reduced recent recovery ({float(avg_rest):.1f} hours average rest)"))
    if _finite_positive(row.get("duty_density_30d_personal_deviation")):
        value = float(row["duty_density_30d_personal_deviation"])
        candidates.append((abs(value), f"higher duty density ({value:+.2f} vs personal reference)"))
    if _finite_positive(row.get("incident_count_30d_personal_deviation")):
        value = float(row["incident_count_30d_personal_deviation"])
        candidates.append((abs(value), f"recent incident exposure ({value:+.1f} vs personal reference)"))
    deployment = row.get("deployment_days_30d")
    if deployment is not None and pd.notna(deployment) and float(deployment) > 0:
        candidates.append((min(float(deployment) / 30.0, 1.0), f"sustained deployment exposure ({float(deployment):.0f} recent deployment days)"))
    for column, label in [
        ("duty_hours_30d_cohort_relative_deviation", "duty load above the cohort reference"),
        ("duty_hours_30d_operational_relative_deviation", "duty load above the operational reference"),
    ]:
        if _finite_positive(row.get(column)):
            candidates.append((abs(float(row[column])), label))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [f"Contributing operational signal: {text}." for _, text in candidates[:max_items]]


def build_decision_output(
    phase4_predictions: pd.DataFrame,
    feature_frame: pd.DataFrame,
    calibrated_probabilities: Iterable[float],
    *,
    selected_threshold: float,
    model_version: str,
    config: DecisionConfig,
) -> pd.DataFrame:
    probs = np.asarray(list(calibrated_probabilities), dtype=float)
    if len(probs) != len(phase4_predictions) or len(probs) != len(feature_frame):
        raise ValueError("Prediction and feature rows must be aligned")
    bands = assign_risk_band(probs, config)
    signals = decision_signal(probs, selected_threshold)

    rows = []
    for idx in range(len(feature_frame)):
        explanation = generate_explanations(feature_frame.iloc[idx]) if signals[idx] == "EARLY_WARNING" else []
        rows.append(explanation)

    return pd.DataFrame(
        {
            "person_id": phase4_predictions["person_id"].astype(str).to_numpy(),
            "date": pd.to_datetime(phase4_predictions["date"], errors="raise").dt.strftime("%Y-%m-%d").to_numpy(),
            "welfare_risk_probability": probs,
            "risk_band": bands,
            "threshold_decision": signals,
            "selected_threshold": float(selected_threshold),
            "model_phase": "PHASE_5",
            "model_version": model_version,
            "contributing_operational_signals": [" | ".join(x) if x else None for x in rows],
        }
    )


def config_dict(config: DecisionConfig) -> dict[str, Any]:
    return asdict(config)
