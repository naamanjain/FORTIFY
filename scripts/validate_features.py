#!/usr/bin/env python3
"""Validate a Phase 2 person-day feature table without doing model inference."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.ml.feature_engineering import FORBIDDEN_FEATURE_NAMES


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate FORTIFY Phase 2 features")
    parser.add_argument("--input", required=True)
    parser.add_argument("--personnel", type=int)
    parser.add_argument("--days", type=int)
    args = parser.parse_args()

    path = Path(args.input)
    df = pd.read_csv(path, parse_dates=["date"])
    errors: list[str] = []
    if {"person_id", "date"} - set(df.columns):
        errors.append("Missing person_id/date columns")
    if df[["person_id", "date"]].duplicated().any():
        errors.append("Duplicate person/date rows")
    if df.empty:
        errors.append("Feature dataset is empty")
    forbidden = FORBIDDEN_FEATURE_NAMES.intersection(df.columns)
    if forbidden:
        errors.append(f"Forbidden feature labels: {sorted(forbidden)}")
    if args.personnel is not None and df.person_id.nunique() != args.personnel:
        errors.append(f"Expected {args.personnel} personnel, found {df.person_id.nunique()}")
    if args.days is not None and len(df) != df.person_id.nunique() * args.days:
        errors.append("Row count does not equal personnel × days")
    for col in ["duty_density_7d", "duty_density_30d"]:
        if col in df and ((df[col] < 0) | (df[col] > 1)).any():
            errors.append(f"Invalid range in {col}")
    if "wellness_available_today" in df and df["wellness_available_today"].isin([True, False]).all():
        pass
    score_cols = [c for c in df.columns if c.endswith("_latest") or c.endswith("_7d_mean") or c.endswith("_30d_mean")]
    for col in score_cols:
        if any(x in col for x in ("mood", "energy", "sleep_quality", "perceived_stress", "workload_manageability")):
            vals = df[col].dropna()
            if not vals.empty and ((vals < 1) | (vals > 5)).any():
                errors.append(f"Invalid wellness range in {col}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"VALIDATION PASSED: {len(df):,} rows, {len(df.columns) - 2:,} features")
    print(f"Personnel: {df.person_id.nunique():,}")
    print(f"Date range: {df.date.min().date()} to {df.date.max().date()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
