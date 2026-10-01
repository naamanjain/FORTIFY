"""Alert-fatigue simulation for FORTIFY.

Runs the deterministic alert policy over the full generated decision stream
(180 days × 500 personnel) and measures the reviewer workload a welfare
officer would actually experience:

* new cases per day and per person (with the daily budget applied)
* how many person-days became cases vs. would have under "alert every day"
* persistent-evidence days on open cases (no new work, but visible)
* suppressions by budget (auditable, not silent)
* unresolved backlog at the end of the horizon
* the duplicate-alert count the policy removed, which is the direct measure
  of the alert fatigue it prevents

This script is evidence for the alert-policy design; it changes nothing.

Usage: python scripts/simulate_alert_fatigue.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.ml.alert_policy import AlertPolicyConfig, evaluate_alert_policy  # noqa: E402

DECISIONS = ROOT / "data" / "generated" / "risk_decisions.csv"
OUTPUT = ROOT / "artifacts" / "benchmark" / "alert_fatigue.json"


def main() -> int:
    if not DECISIONS.exists():
        raise SystemExit("risk_decisions.csv missing; run scripts/build_all.py first")
    decisions = pd.read_csv(DECISIONS, usecols=["person_id", "date", "welfare_risk_probability", "risk_band", "threshold_decision"])
    decisions["date"] = pd.to_datetime(decisions["date"])

    config = AlertPolicyConfig()
    queue = evaluate_alert_policy(decisions, config)

    dates = sorted(decisions["date"].unique())
    span_days = len(dates)
    n_people = int(decisions["person_id"].nunique())

    # Naive counterfactual: a case every day the calibrated threshold fires.
    naive = decisions[decisions["threshold_decision"] == "EARLY_WARNING"]
    naive_cases = int(len(naive))

    created = queue[queue["case_created"]] if not queue.empty else queue
    suppressed = queue[queue["suppressed_by_budget"]] if not queue.empty else queue
    persistent = queue[queue["alert_state"] == "PERSISTENT"] if not queue.empty else queue

    per_day = created.groupby("date").size() if not created.empty else pd.Series(dtype=int)
    per_person = created.groupby("person_id").size() if not created.empty else pd.Series(dtype=int)

    # A simple open-case backlog estimate: a case is "open" from creation until
    # a RECOVERED signal appears for that person (human closure is not
    # simulated here; RECOVERED is the earliest a human would close it).
    recovered_dates = (queue[queue["alert_state"] == "RECOVERED"].groupby("person_id")["date"].min()
                       if not queue.empty else pd.Series(dtype="datetime64[ns]"))
    backlog = 0
    unresolved_cases = 0
    for person_id, group in created.groupby("person_id"):
        first_open = group["date"].min()
        close_by = recovered_dates.get(person_id)
        if close_by is None or pd.isna(close_by) or close_by < first_open:
            unresolved_cases += 1
            backlog += span_days - (first_open - dates[0]).days
        else:
            backlog += max(0, (close_by - first_open).days)

    report = {
        "policy_version": "alert-policy-v1",
        "config": config.as_dict(),
        "population": {"personnel": n_people, "days": span_days,
                       "person_days": int(len(decisions))},
        "naive_threshold_fires": naive_cases,
        "policy_new_cases": int(len(created)),
        "duplicate_alerts_prevented": int(naive_cases - len(created) - len(suppressed)),
        "suppressed_by_budget": int(len(suppressed)),
        "persistent_evidence_days": int(len(persistent)),
        "cases_per_day_mean": float(per_day.mean()) if len(per_day) else 0.0,
        "cases_per_day_max": int(per_day.max()) if len(per_day) else 0,
        "days_over_budget": int((per_day > config.max_daily_review_cases).sum()),
        "cases_per_person_mean": float(per_person.mean()) if len(per_person) else 0.0,
        "cases_per_person_max": int(per_person.max()) if len(per_person) else 0,
        "people_with_no_case": int(n_people - per_person.size),
        "estimated_open_case_days": int(backlog),
        "unresolved_cases_at_horizon_end": int(unresolved_cases),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Population: {n_people} personnel over {span_days} days ({len(decisions):,} person-days)")
    print(f"Naive 'alert every threshold day' cases : {naive_cases:,}")
    print(f"Policy new cases (after rules + budget) : {report['policy_new_cases']:,}")
    print(f"Duplicate alerts prevented              : {report['duplicate_alerts_prevented']:,}")
    print(f"Suppressed by budget (recorded)         : {report['suppressed_by_budget']:,}")
    print(f"Persistent-evidence days on open cases  : {report['persistent_evidence_days']:,}")
    print(f"New cases per day: mean {report['cases_per_day_mean']:.2f}, max {report['cases_per_day_max']}")
    print(f"New cases per person: mean {report['cases_per_person_mean']:.2f}, max {report['cases_per_person_max']}")
    print(f"People with no case in 180 days         : {report['people_with_no_case']}")
    print(f"Report: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())