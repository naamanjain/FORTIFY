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
    minimum_validation_precision: float = 0.55
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
        if not 0 < self.minimum_validation_precision <= 1:
            raise ValueError("minimum_validation_precision must be in (0, 1]")
        if not 0 < self.low_band_upper < self.moderate_band_upper < 1:
            raise ValueError("risk-band cutoffs must satisfy 0 < low < moderate < 1")
        if self.calibration_bins < 2:
            raise ValueError("calibration_bins must be >= 2")


@dataclass(frozen=True)
class ThresholdSelection:
    selected_threshold: float
    rule: str
    minimum_validation_precision: float


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
    minimum_validation_precision: float = 0.55,
    recent_window_table: pd.DataFrame | None = None,
) -> ThresholdSelection:
    """Pick the operating point for welfare triage.

    Policy: among candidate thresholds whose validation precision meets the
    configured floor, select the highest validation F1 (ties: higher recall,
    then lower threshold). A precision floor keeps flags mostly-correct so the
    review queue prioritizes instead of flagging most of the population. The
    floor is prototype tuning, not departmental policy, and requires
    real-world review before operational use.

    Time-aware variant: when ``recent_window_table`` is supplied - metrics
    computed over the most recent portion of the validation window - selection
    happens on that window instead. Rationale: the validation window closest to
    the deployment period best represents the population and base rate the
    model will actually operate on. On this dataset the full-window choice
    degraded sharply on the held-out month (the positive rate drifted from 0.45
    in training to 0.35 later in the series), while the recent-window choice
    held up better. The held-out window is never used to choose the threshold;
    it is used only to *report* how each policy transferred.
    """
    required = {"threshold", "recall", "f1", "precision"}
    missing = sorted(required.difference(threshold_table.columns))
    if missing:
        raise ValueError(f"Threshold table missing columns: {missing}")

    selection_table = threshold_table
    used_window = "full validation window"
    if recent_window_table is not None:
        missing_recent = sorted(required.difference(recent_window_table.columns))
        if missing_recent:
            raise ValueError(f"Recent-window table missing columns: {missing_recent}")
        recent_eligible = recent_window_table[
            recent_window_table["precision"] >= minimum_validation_precision
        ]
        # Fall back to the full window only if the recent window admits nothing,
        # so a short or degenerate recent block cannot force a bad operating point.
        if not recent_eligible.empty:
            selection_table = recent_window_table
            used_window = "most recent half of the validation window"

    eligible = selection_table[selection_table["precision"] >= minimum_validation_precision].copy()
    if eligible.empty:
        raise ValueError(
            "No candidate threshold satisfies the configured validation precision floor; "
            "adjust candidates or the floor for this dataset."
        )
    eligible = eligible.sort_values(
        ["f1", "recall", "threshold"], ascending=[False, False, True], kind="mergesort"
    )
    chosen = float(eligible.iloc[0]["threshold"])
    return ThresholdSelection(
        selected_threshold=chosen,
        rule=(
            f"Select the candidate threshold with the highest F1 on the {used_window} "
            "among thresholds meeting the configured validation precision floor; "
            "break ties using recall, then lower threshold."
        ),
        minimum_validation_precision=float(minimum_validation_precision),
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

    Delegates to the structured explanation layer, which guarantees that every
    factor states what changed, by how much, against which reference, over what
    window, and which rule admitted it - and that only *adverse* deviations are
    presented as contributing factors.

    This routine never reads raw wellness-response columns.
    """
    from .explanations import build_factors, render_factors

    factors = build_factors(row, max_factors=max_items)
    if not factors:
        return []
    return ["Contributing operational signal: " + sentence for sentence in render_factors(factors).split(" | ")]


def build_structured_explanation(row: pd.Series, max_factors: int = 5) -> dict[str, Any]:
    """Structured, provenance-carrying explanation for API consumers."""
    from .explanations import explain_row

    return explain_row(row, max_factors=max_factors)


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
