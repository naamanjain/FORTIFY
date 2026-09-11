from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.ml.intervention_config import InterventionPolicyConfig
from backend.app.ml.intervention_policy import build_intervention_recommendations, config_dict


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the FORTIFY Phase 6 welfare-support intervention layer.")
    parser.add_argument("--predictions", default="data/generated/risk_decisions.csv")
    parser.add_argument("--features", default="data/generated/person_day_features_baseline.csv")
    parser.add_argument("--output", default="data/generated/intervention_recommendations.csv")
    parser.add_argument("--report", default="data/generated/intervention_generation_report.json")
    parser.add_argument("--policy-version", default="phase6-v1")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    predictions_path = ROOT / args.predictions
    features_path = ROOT / args.features
    output_path = ROOT / args.output
    report_path = ROOT / args.report

    predictions = pd.read_csv(predictions_path)
    features = pd.read_csv(features_path)
    config = InterventionPolicyConfig(policy_version=args.policy_version)
    output = build_intervention_recommendations(predictions, features, config=config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(output_path, index=False)

    report = {
        "phase": 6,
        "status": "complete",
        "rows": int(len(output)),
        "unique_persons": int(output["person_id"].nunique()),
        "risk_band_counts": {str(k): int(v) for k, v in output["risk_band"].value_counts().to_dict().items()},
        "action_counts": {str(k): int(v) for k, v in output["recommended_action"].value_counts().to_dict().items()},
        "human_review_count": int(output["requires_human_review"].sum()),
        "policy": config_dict(config),
        "safety": {
            "synthetic_data": True,
            "medical_diagnosis": False,
            "disciplinary_action": False,
            "autonomous_execution": False,
            "human_oversight_required_for_review": True,
        },
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Intervention recommendations: {len(output):,}")
    print(f"Unique personnel: {output['person_id'].nunique():,}")
    print("Action counts:")
    for action, count in output["recommended_action"].value_counts().items():
        print(f"  {action}: {count:,}")
    try:
        display_path = output_path.relative_to(ROOT)
    except ValueError:
        display_path = output_path
    print(f"Output: {display_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
