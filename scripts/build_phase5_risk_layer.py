from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.ml.model_config import ModelConfig
from backend.app.ml.model_training import RiskModelTrainer
from backend.app.ml.risk_decision import (
    DecisionConfig,
    analyze_thresholds,
    apply_calibrator,
    build_decision_output,
    calibration_diagnostics,
    config_dict,
    fit_platt_calibrator,
    select_operating_threshold,
)
from backend.app.ml.target_engineering import build_future_wellness_target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the FORTIFY Phase 5 risk decision layer.")
    parser.add_argument("--features", default="data/generated/person_day_features_baseline.csv")
    parser.add_argument("--phase4-model", default="artifacts/phase4/fortify_phase4_logistic_regression.joblib")
    parser.add_argument("--phase4-metadata", default="artifacts/phase4/model_metadata.json")
    parser.add_argument("--phase4-predictions", default="data/generated/risk_predictions.csv")
    parser.add_argument("--output-dir", default="artifacts/phase5")
    parser.add_argument("--prediction-output", default="data/generated/risk_decisions.csv")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    features_path = ROOT / args.features
    phase4_model_path = ROOT / args.phase4_model
    metadata_path = ROOT / args.phase4_metadata
    phase4_predictions_path = ROOT / args.phase4_predictions
    output_dir = ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    features = pd.read_csv(features_path)
    phase4_predictions = pd.read_csv(phase4_predictions_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    feature_columns = metadata["feature_columns"]
    model = joblib.load(phase4_model_path)

    trainer = RiskModelTrainer(ModelConfig(random_state=args.seed))
    targets = build_future_wellness_target(features)
    frame = features.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    frame = frame.merge(targets, on=["person_id", "date"], how="left", validate="one_to_one", sort=False)
    labeled = frame[frame["target"].notna()].copy()
    labeled["target"] = labeled["target"].astype(int)
    train, valid, test = trainer.split_by_date(labeled)

    valid_raw = model.predict_proba(valid[feature_columns])[:, 1]
    test_raw = model.predict_proba(test[feature_columns])[:, 1]
    all_raw = model.predict_proba(features[feature_columns])[:, 1]

    decision_config = DecisionConfig(random_state=args.seed)
    calibrator = fit_platt_calibrator(valid_raw, valid["target"], random_state=args.seed)
    valid_calibrated = apply_calibrator(calibrator, valid_raw)
    test_calibrated = apply_calibrator(calibrator, test_raw)
    all_calibrated = apply_calibrator(calibrator, all_raw)

    threshold_table = analyze_thresholds(
        valid["target"],
        valid_calibrated,
        decision_config.decision_threshold_candidates,
    )
    selection = select_operating_threshold(
        threshold_table,
        minimum_validation_recall=decision_config.minimum_validation_recall,
    )

    validation_calibration = calibration_diagnostics(valid["target"], valid_calibrated, decision_config.calibration_bins)
    test_calibration = calibration_diagnostics(test["target"], test_calibrated, decision_config.calibration_bins)
    test_operating = analyze_thresholds(test["target"], test_calibrated, [selection.selected_threshold]).iloc[0].to_dict()
    validation_operating = analyze_thresholds(valid["target"], valid_calibrated, [selection.selected_threshold]).iloc[0].to_dict()

    aligned_features = features.copy().reset_index(drop=True)
    output = build_decision_output(
        phase4_predictions.reset_index(drop=True),
        aligned_features,
        all_calibrated,
        selected_threshold=selection.selected_threshold,
        model_version="phase5-v1",
        config=decision_config,
    )
    output.to_csv(ROOT / args.prediction_output, index=False)

    threshold_table.to_csv(output_dir / "threshold_analysis.csv", index=False)
    joblib.dump(calibrator, output_dir / "platt_calibrator.joblib")

    model_card = {
        "phase": 5,
        "status": "complete",
        "model_identity": {
            "base_model": metadata["model_type"],
            "base_model_phase": 4,
            "model_features": metadata["feature_count"],
            "phase5_model_version": "phase5-v1",
            "probability_layer": "validation-fitted Platt calibration applied to Phase 4 probabilities",
        },
        "target": {
            "name": metadata["target_name"],
            "definition": metadata["target_definition"],
            "horizon_days": metadata["target_horizon_days"],
            "source": metadata["target_source"],
        },
        "data": {
            "rows": int(len(features)),
            "usable_labeled_samples": int(len(labeled)),
            "excluded_unlabeled_rows": int(len(features) - len(labeled)),
            "wellness_predictors_excluded": True,
            "splits": metadata["temporal_splits"],
        },
        "threshold_selection": {
            "candidate_thresholds": list(decision_config.decision_threshold_candidates),
            "selection": config_dict(selection),
            "selected_threshold": selection.selected_threshold,
            "validation_operating_point": validation_operating,
            "test_operating_point": test_operating,
            "test_labels_not_used_for_selection": True,
            "rationale": "Early-warning operation prioritizes sensitivity while retaining a validation-supported precision/F1 trade-off. The prior 0.50 operating point had low recall and is not retained as the Phase 5 decision threshold.",
        },
        "risk_bands": {
            "LOW": f"probability < {decision_config.low_band_upper}",
            "MODERATE": f"{decision_config.low_band_upper} <= probability < {decision_config.moderate_band_upper}",
            "HIGH": f"probability >= {decision_config.moderate_band_upper}",
            "interpretation": "Operational/welfare monitoring signals only; not clinical diagnoses.",
        },
        "calibration": {
            "method": "Platt scaling fitted on validation predictions only",
            "validation": validation_calibration,
            "test": test_calibration,
            "test_not_used_for_calibration": True,
        },
        "safety_privacy": {
            "raw_wellness_values_in_prediction_output": False,
            "medical_diagnosis": False,
            "disciplinary_recommendation": False,
            "purpose": "early-support/welfare monitoring decision support",
            "synthetic_data": True,
        },
        "limitations": [
            "The target is a synthetic voluntary self-report observation and is not clinical ground truth.",
            "Many person-days are excluded from supervised evaluation because no future voluntary wellness observation exists in the target horizon.",
            "Thresholds are prototype operating conventions selected from validation data and require real-world policy review before operational use.",
            "Calibration is assessed on temporally held-out data but has not been externally validated.",
            "Operational contributors are associations from model inputs and must not be described as individual causal explanations.",
        ],
    }
    (output_dir / "model_card.json").write_text(json.dumps(model_card, indent=2, sort_keys=True), encoding="utf-8")
    (output_dir / "calibration_report.json").write_text(
        json.dumps({"validation": validation_calibration, "test": test_calibration}, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print(f"Input person-days: {len(features):,}")
    print(f"Usable labeled samples: {len(labeled):,}")
    print(f"Validation selected threshold: {selection.selected_threshold:.3f}")
    print(f"Validation recall at selected threshold: {validation_operating['recall']:.4f}")
    print(f"Validation F1 at selected threshold: {validation_operating['f1']:.4f}")
    print(f"Test ROC AUC (calibrated): {test_calibration['roc_auc']:.4f}")
    print(f"Test Brier score (calibrated): {test_calibration['brier_score']:.4f}")
    print(f"Test recall at locked threshold: {test_operating['recall']:.4f}")
    print(f"Risk decisions written: {len(output):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
