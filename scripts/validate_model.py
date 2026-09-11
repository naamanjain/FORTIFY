from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FORBIDDEN = {
    "stress_label",
    "stress_score",
    "mental_health_label",
    "depression_label",
    "anxiety_label",
    "risk_score",
    "risk_band",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate FORTIFY Phase 4 model artifacts and predictions.")
    parser.add_argument("--metadata", default="artifacts/phase4/model_metadata.json")
    parser.add_argument("--evaluation", default="artifacts/phase4/evaluation_report.json")
    parser.add_argument("--predictions", default="data/generated/risk_predictions.csv")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    metadata = json.loads((ROOT / args.metadata).read_text(encoding="utf-8"))
    report = json.loads((ROOT / args.evaluation).read_text(encoding="utf-8"))
    predictions = pd.read_csv(ROOT / args.predictions)

    required_prediction_cols = {"person_id", "date", "welfare_risk_probability", "risk_level"}
    missing = sorted(required_prediction_cols.difference(predictions.columns))
    if missing:
        raise SystemExit(f"Missing prediction columns: {missing}")
    if FORBIDDEN.intersection(predictions.columns):
        raise SystemExit(f"Forbidden prediction columns: {sorted(FORBIDDEN.intersection(predictions.columns))}")
    if predictions.duplicated(["person_id", "date"]).any():
        raise SystemExit("Duplicate person/date predictions")
    if not predictions["welfare_risk_probability"].between(0, 1).all():
        raise SystemExit("Probability outside [0, 1]")
    if not predictions["risk_level"].isin({"LOW", "MODERATE", "ELEVATED"}).all():
        raise SystemExit("Invalid risk level")
    if metadata["feature_count"] <= 0:
        raise SystemExit("No model features recorded")
    if metadata["wellness_features_excluded"] is not True:
        raise SystemExit("Wellness-feature exclusion contract is missing")
    if report["prediction_rows"] != len(predictions):
        raise SystemExit("Prediction-row report mismatch")

    print(f"VALIDATION PASSED: {len(predictions):,} predictions, {metadata['feature_count']} model features")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
