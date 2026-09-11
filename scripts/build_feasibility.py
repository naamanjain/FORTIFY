from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.ml.feasibility_engineering import build_intervention_feasibility


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build the FORTIFY Phase 7 operational feasibility layer.")
    p.add_argument("--interventions", default="data/generated/intervention_recommendations.csv")
    p.add_argument("--personnel", default="data/generated/personnel.csv")
    p.add_argument("--duty", default="data/generated/duty_events.csv")
    p.add_argument("--recovery", default="data/generated/recovery_events.csv")
    p.add_argument("--leave", default="data/generated/leave_events.csv")
    p.add_argument("--deployment", default="data/generated/deployment_events.csv")
    p.add_argument("--training", default="data/generated/training_events.csv")
    p.add_argument("--output", default="data/generated/intervention_feasibility.csv")
    p.add_argument("--report", default="data/generated/feasibility_generation_report.json")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    load = lambda name: pd.read_csv(ROOT / name)
    interventions = load(args.interventions)
    personnel = load(args.personnel)
    duty = load(args.duty)
    recovery = load(args.recovery)
    leave = load(args.leave)
    deployment = load(args.deployment)
    training = load(args.training)
    output = build_intervention_feasibility(interventions, personnel, duty, recovery, leave, deployment, training)
    out_path = ROOT / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(out_path, index=False)
    report = {
        "phase": 7,
        "status": "complete",
        "rows": int(len(output)),
        "unique_persons": int(output.person_id.nunique()),
        "feasibility_status_counts": {str(k): int(v) for k, v in output.feasibility_status.value_counts().to_dict().items()},
        "constraint_flag_counts": {
            flag: int(sum(1 for value in output["constraint_flags"].fillna("") if flag in {item.strip() for item in value.split("|") if item.strip()}))
            for flag in sorted({item.strip() for value in output["constraint_flags"].fillna("") for item in value.split("|") if item.strip()})
        },
        "policy_version": "phase7-v1",
        "safety": {"medical_diagnosis": False, "disciplinary_action": False, "automatic_adverse_action": False, "human_oversight": True},
    }
    (ROOT / args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Feasibility results: {len(output):,}")
    print(f"Unique personnel: {output.person_id.nunique():,}")
    print(output.feasibility_status.value_counts().to_string())
    print(f"Output: {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
