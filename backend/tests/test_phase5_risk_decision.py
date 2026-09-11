from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from backend.app.ml.risk_decision import (
    DecisionConfig,
    analyze_thresholds,
    assign_risk_band,
    build_decision_output,
    calibration_diagnostics,
    decision_signal,
    fit_platt_calibrator,
    select_operating_threshold,
    threshold_metrics,
)


def test_threshold_metrics_are_complete() -> None:
    y = [0, 0, 1, 1, 1]
    p = [0.10, 0.30, 0.40, 0.70, 0.90]
    result = threshold_metrics(y, p, 0.50)
    assert set([
        "precision", "recall", "f1", "specificity", "false_positive_rate",
        "false_negative_rate", "predicted_positive_count", "predicted_positive_rate",
    ]).issubset(result)
    assert result["predicted_positive_count"] == 2


def test_threshold_selection_uses_validation_recall_floor() -> None:
    table = analyze_thresholds([0, 0, 1, 1, 1], [0.05, 0.20, 0.35, 0.60, 0.90], [0.20, 0.40, 0.60])
    selection = select_operating_threshold(table, minimum_validation_recall=0.60)
    assert selection.selected_threshold == 0.20


def test_risk_bands_and_decision_signal_are_deterministic() -> None:
    config = DecisionConfig()
    p = [0.10, 0.25, 0.49, 0.50, 0.80]
    assert assign_risk_band(p, config).tolist() == ["LOW", "MODERATE", "MODERATE", "HIGH", "HIGH"]
    assert decision_signal(p, 0.25).tolist() == ["NO_EARLY_WARNING", "EARLY_WARNING", "EARLY_WARNING", "EARLY_WARNING", "EARLY_WARNING"]


def test_calibration_is_validation_only_and_deterministic() -> None:
    y = np.array([0, 0, 1, 1, 1, 0, 1, 0])
    p = np.array([0.1, 0.2, 0.3, 0.7, 0.9, 0.4, 0.6, 0.2])
    c1 = fit_platt_calibrator(p, y, random_state=42)
    c2 = fit_platt_calibrator(p, y, random_state=42)
    assert np.allclose(c1.predict_proba(p.reshape(-1, 1)), c2.predict_proba(p.reshape(-1, 1)))
    diag = calibration_diagnostics(y, c1.predict_proba(p.reshape(-1, 1))[:, 1], bins=5)
    assert 0 <= diag["brier_score"] <= 1
    assert diag["roc_auc"] is not None


def test_explanations_are_operational_and_do_not_expose_wellness() -> None:
    feature = pd.Series({
        "duty_hours_7d_personal_deviation": 12.0,
        "night_shifts_30d_personal_deviation": 3.0,
        "avg_rest_7d": 5.5,
        "duty_density_30d_personal_deviation": 0.2,
        "deployment_days_30d": 20,
        "perceived_stress_latest": 5,
    })
    predictions = pd.DataFrame({
        "person_id": ["P-1"],
        "date": ["2026-01-01"],
        "welfare_risk_probability": [0.80],
    })
    output = build_decision_output(
        predictions,
        pd.DataFrame([feature]),
        [0.80],
        selected_threshold=0.25,
        model_version="phase5-v1",
        config=DecisionConfig(),
    )
    text = output.loc[0, "contributing_operational_signals"]
    assert "perceived_stress" not in str(text)
    assert "Contributing operational signal" in str(text)
    assert "EARLY_WARNING" == output.loc[0, "threshold_decision"]


def test_phase5_validation_cli_accepts_clean_output(tmp_path: Path) -> None:
    pred = pd.DataFrame({
        "person_id": ["P-1"], "date": ["2026-01-01"], "welfare_risk_probability": [0.80],
        "risk_band": ["HIGH"], "threshold_decision": ["EARLY_WARNING"], "selected_threshold": [0.25],
        "model_phase": ["PHASE_5"], "model_version": ["phase5-v1"],
        "contributing_operational_signals": ["Contributing operational signal: elevated recent duty hours."],
    })
    local_tmp = Path("data/generated/.phase5_test_tmp")
    local_tmp.mkdir(parents=True, exist_ok=True)
    pred_path = local_tmp / "pred.csv"
    card_path = local_tmp / "card.json"
    pred.to_csv(pred_path, index=False)
    card = {
        "model_identity": {"model_features": 218},
        "threshold_selection": {"selected_threshold": 0.25, "test_labels_not_used_for_selection": True},
        "calibration": {"test_not_used_for_calibration": True},
    }
    card_path.write_text(json.dumps(card), encoding="utf-8")

    script = Path("scripts/validate_phase5_risk_layer.py")
    completed = subprocess.run(
        [sys.executable, str(script), "--predictions", str(pred_path), "--model-card", str(card_path)],
        cwd=Path.cwd(), capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stderr
    for path in local_tmp.iterdir():
        path.unlink()
    local_tmp.rmdir()
