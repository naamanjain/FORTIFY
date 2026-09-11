#!/usr/bin/env python3
"""Build Phase 2 person-day features from Phase 1 CSVs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.ml import FeatureConfig, FeatureEngineer  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build FORTIFY person-day features")
    parser.add_argument("--input", default="data/generated")
    parser.add_argument("--output", default="data/generated")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--short-rest-threshold-hours", type=float, default=6.0)
    parser.add_argument("--recovery-target-hours", type=float, default=8.0)
    args = parser.parse_args()

    config = FeatureConfig(
        short_rest_threshold_hours=args.short_rest_threshold_hours,
        recovery_target_hours=args.recovery_target_hours,
    )
    engineer = FeatureEngineer(args.input, config=config)
    result = engineer.write_features(
        Path(args.output) / "person_day_features.csv",
        start_date=args.start_date,
        end_date=args.end_date,
    )
    report = {
        "rows": int(len(result)),
        "personnel": int(result["person_id"].nunique()),
        "start_date": str(result["date"].min().date()),
        "end_date": str(result["date"].max().date()),
        "feature_count": int(len(result.columns) - 2),
        "config": engineer.metadata(),
        "phase": "Phase 2 — Feature Engineering",
        "note": "No model training, risk score, diagnosis, recommendation, or optimization is performed.",
    }
    report_path = Path(args.output) / "feature_generation_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Person-day rows: {len(result):,}")
    print(f"Personnel: {result['person_id'].nunique():,}")
    print(f"Date range: {result['date'].min().date()} to {result['date'].max().date()}")
    print(f"Features: {len(result.columns) - 2}")
    print(f"Output: {Path(args.output) / 'person_day_features.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
