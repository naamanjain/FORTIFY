from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

FORBIDDEN = {
    "stress_label", "stress_score", "mental_health_label",
    "depression_label", "anxiety_label", "risk_score", "risk_band",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Phase 3 baseline-extended features")
    parser.add_argument("--input", default="data/generated/person_day_features.csv")
    parser.add_argument("--personnel", type=int)
    parser.add_argument("--days", type=int)
    args = parser.parse_args()
    df = pd.read_csv(args.input)
    required = {"person_id", "date", "role", "deployment_type", "unit_type", "duty_hours_7d"}
    missing = required.difference(df.columns)
    if missing:
        raise SystemExit(f"VALIDATION FAILED: missing columns {sorted(missing)}")
    if df.duplicated(["person_id", "date"]).any():
        raise SystemExit("VALIDATION FAILED: duplicate person/date rows")
    if args.personnel is not None and df["person_id"].nunique() != args.personnel:
        raise SystemExit(f"VALIDATION FAILED: expected {args.personnel} personnel, found {df["person_id"].nunique()}")
    if args.days is not None and len(df) != df["person_id"].nunique() * args.days:
        raise SystemExit("VALIDATION FAILED: row count does not equal personnel × days")
    forbidden = FORBIDDEN.intersection(df.columns)
    if forbidden:
        raise SystemExit(f"VALIDATION FAILED: forbidden columns {sorted(forbidden)}")
    required_phase3 = [
        "duty_hours_7d_personal_history_mean",
        "duty_hours_7d_cohort_baseline_mean",
        "duty_hours_7d_operational_baseline_mean",
        "personal_baseline_semantics",
    ]
    missing_p3 = [c for c in required_phase3 if c not in df.columns]
    if missing_p3:
        raise SystemExit(f"VALIDATION FAILED: missing Phase 3 outputs {missing_p3}")
    print(f"VALIDATION PASSED: {len(df):,} rows, {len(df.columns):,} columns")
    print(f"Date range: {df['date'].min()} → {df['date'].max()}")
    print(f"Unique personnel: {df['person_id'].nunique():,}")


if __name__ == "__main__":
    main()
