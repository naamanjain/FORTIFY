"""Build the daily review queue from Phase 5 risk decisions.

The predictive layer scores every person-day; this step decides which of those
scores become human work. It applies the deterministic alert policy
(persistence, duplicate suppression, escalation, recovery, daily budget) and
writes `review_queue.csv`, which the workflow layer materializes cases from.

Running the model without this layer would create one workflow case per
threshold-firing person-day - on the demo world that is ~45,700 cases over 180
days. The policy reduces that to the day's budgeted queue while recording
every suppressed candidate for audit.

Usage: python scripts/build_review_queue.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.ml.alert_policy import AlertPolicyConfig, evaluate_alert_policy  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply the alert policy to risk decisions.")
    parser.add_argument("--decisions", default="data/generated/risk_decisions.csv")
    parser.add_argument("--output", default="data/generated/review_queue.csv")
    parser.add_argument("--report", default="data/generated/review_queue_report.json")
    parser.add_argument("--min-score", type=float, default=0.40)
    parser.add_argument("--persistence-days", type=int, default=2)
    parser.add_argument("--max-daily-cases", type=int, default=25)
    args = parser.parse_args()

    decisions_path = ROOT / args.decisions
    if not decisions_path.exists():
        raise SystemExit(f"Input not found: {decisions_path}")
    decisions = pd.read_csv(decisions_path, usecols=[
        "person_id", "date", "welfare_risk_probability", "risk_band", "threshold_decision"])

    config = AlertPolicyConfig(
        minimum_score=args.min_score,
        persistence_days=args.persistence_days,
        max_daily_review_cases=args.max_daily_cases,
    )
    queue = evaluate_alert_policy(decisions, config)

    out_path = ROOT / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    queue.to_csv(out_path, index=False)

    created = queue[queue["case_created"]] if not queue.empty else queue
    suppressed = queue[queue["suppressed_by_budget"]] if not queue.empty else queue
    naive = int((decisions["threshold_decision"] == "EARLY_WARNING").sum())
    report = {
        "policy_version": "alert-policy-v1",
        "config": config.as_dict(),
        "person_days_scored": int(len(decisions)),
        "naive_threshold_fires": naive,
        "queue_rows": int(len(queue)),
        "cases_created": int(len(created)),
        "suppressed_by_budget": int(len(suppressed)),
        "state_counts": queue["alert_state"].value_counts().to_dict() if not queue.empty else {},
    }
    (ROOT / args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Review queue: {report['cases_created']} cases created, "
          f"{report['suppressed_by_budget']} suppressed by budget, "
          f"{naive:,} threshold days suppressed by policy rules")
    print(f"Output: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())