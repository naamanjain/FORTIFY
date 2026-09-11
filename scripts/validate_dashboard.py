from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.routes.dashboard import _dashboard_frame

EXPECTED_COLUMNS = {
    "person_id", "date", "welfare_risk_probability", "risk_band",
    "recommended_action", "priority", "feasibility_status",
}
FORBIDDEN = {"mood_score", "energy_score", "sleep_quality", "perceived_stress", "support_request"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate FORTIFY Phase 9 dashboard data compatibility")
    parser.add_argument("--data-dir", default="data/generated")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    required = [
        "intervention_recommendations.csv",
        "intervention_feasibility.csv",
        "personnel.csv",
    ]
    missing = [name for name in required if not (data_dir / name).exists()]
    if missing:
        print(f"VALIDATION FAILED: missing artifacts: {missing}")
        return 1

    df = _dashboard_frame()
    if len(df) != 90000:
        print(f"VALIDATION FAILED: expected 90000 joined rows, got {len(df)}")
        return 1
    if EXPECTED_COLUMNS - set(df.columns):
        print(f"VALIDATION FAILED: missing columns: {sorted(EXPECTED_COLUMNS - set(df.columns))}")
        return 1
    if df[["person_id", "date"]].duplicated().any():
        print("VALIDATION FAILED: duplicate person/date records")
        return 1
    if not df["risk_band"].isin({"LOW", "MODERATE", "HIGH"}).all():
        print("VALIDATION FAILED: invalid risk band")
        return 1
    if any(name in df.columns for name in FORBIDDEN):
        print("VALIDATION FAILED: raw wellness fields exposed")
        return 1
    print(f"PHASE 9 DASHBOARD VALIDATION PASSED: {len(df):,} rows, {len(df.columns)} joined fields")
    print(f"Personnel: {df['person_id'].nunique():,}")
    print(f"Date range: {df['date'].min()} -> {df['date'].max()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
