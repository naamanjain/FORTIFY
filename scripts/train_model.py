from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.ml.model_config import ModelConfig
from backend.app.ml.model_training import RiskModelTrainer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the FORTIFY Phase 4 predictive risk model.")
    parser.add_argument("--input", default="data/generated/person_day_features_baseline.csv")
    parser.add_argument("--output-dir", default="artifacts/phase4")
    parser.add_argument("--prediction-output", default="data/generated/risk_predictions.csv")
    parser.add_argument("--target-horizon-days", type=int, default=7)
    parser.add_argument("--target-threshold", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-training-samples", type=int, default=100)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = ROOT / args.input
    output_dir = ROOT / args.output_dir
    prediction_path = ROOT / args.prediction_output
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    frame = pd.read_csv(input_path)
    config = ModelConfig(
        target_horizon_days=args.target_horizon_days,
        target_threshold=args.target_threshold,
        random_state=args.seed,
        min_training_samples=args.min_training_samples,
    )
    trainer = RiskModelTrainer(config)
    result = trainer.train(frame)
    trainer.save_artifacts(
        result,
        output_dir / "fortify_phase4_logistic_regression.joblib",
        output_dir / "model_metadata.json",
    )
    predictions = trainer.predict(result["model"], frame, result["features"], config.risk_thresholds)
    prediction_path.parent.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(prediction_path, index=False)

    report = {
        "phase": 4,
        "model": result["metadata"],
        "prediction_output": str(prediction_path.relative_to(ROOT)) if prediction_path.is_relative_to(ROOT) else str(prediction_path),
        "prediction_rows": int(len(predictions)),
    }
    (output_dir / "evaluation_report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    print(f"Usable labeled samples: {result['metadata']['usable_samples']}")
    print(f"Excluded unlabeled rows: {result['metadata']['excluded_rows']}")
    print(f"Feature count used: {result['metadata']['feature_count']}")
    print(f"Train/validation/test: {result['metadata']['temporal_splits']['train']['rows']}/"
          f"{result['metadata']['temporal_splits']['validation']['rows']}/"
          f"{result['metadata']['temporal_splits']['test']['rows']}")
    print(f"Validation ROC AUC: {result['metadata']['validation_metrics']['roc_auc']}")
    print(f"Test ROC AUC: {result['metadata']['test_metrics']['roc_auc']}")
    print(f"Test average precision: {result['metadata']['test_metrics']['average_precision']}")
    print(f"Predictions written: {len(predictions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
