from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FORBIDDEN = {
    "stress_score", "stress_label", "mental_health_label", "depression_label",
    "anxiety_label", "risk_score", "perceived_stress_latest", "mood_latest",
    "sleep_quality_latest", "energy_latest", "support_request_recent",
}
REQUIRED = {
    "person_id", "date", "welfare_risk_probability", "risk_band",
    "threshold_decision", "selected_threshold", "model_phase", "model_version",
    "contributing_operational_signals",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the FORTIFY Phase 5 risk decision layer.")
    parser.add_argument("--predictions", default="data/generated/risk_decisions.csv")
    parser.add_argument("--model-card", default="artifacts/phase5/model_card.json")
    args = parser.parse_args()

    pred = pd.read_csv(ROOT / args.predictions)
    card = json.loads((ROOT / args.model_card).read_text(encoding="utf-8"))

    missing = sorted(REQUIRED.difference(pred.columns))
    if missing:
        raise SystemExit(f"Missing prediction columns: {missing}")
    forbidden = sorted(FORBIDDEN.intersection(pred.columns))
    if forbidden:
        raise SystemExit(f"Forbidden privacy/clinical columns: {forbidden}")
    if pred.duplicated(["person_id", "date"]).any():
        raise SystemExit("Duplicate person/date predictions")
    if not pred["welfare_risk_probability"].between(0, 1).all():
        raise SystemExit("Probability outside [0,1]")
    if not pred["risk_band"].isin({"LOW", "MODERATE", "HIGH"}).all():
        raise SystemExit("Invalid risk band")
    if not pred["threshold_decision"].isin({"EARLY_WARNING", "NO_EARLY_WARNING"}).all():
        raise SystemExit("Invalid threshold decision")
    threshold = float(card["threshold_selection"]["selected_threshold"])
    expected = np.where(pred["welfare_risk_probability"] >= threshold, "EARLY_WARNING", "NO_EARLY_WARNING")
    if not np.array_equal(expected, pred["threshold_decision"].to_numpy()):
        raise SystemExit("Threshold decision does not match locked threshold")
    if card["threshold_selection"]["test_labels_not_used_for_selection"] is not True:
        raise SystemExit("Threshold selection provenance invalid")
    if card["calibration"]["test_not_used_for_calibration"] is not True:
        raise SystemExit("Calibration provenance invalid")
    if card["model_identity"]["model_features"] <= 0:
        raise SystemExit("Invalid feature count")
    print(f"VALIDATION PASSED: {len(pred):,} decisions, threshold={threshold:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
