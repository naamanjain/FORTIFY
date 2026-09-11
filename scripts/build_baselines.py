from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from backend.app.ml.baseline_engineering import BaselineEngineer
from backend.app.ml.baseline_config import BaselineConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Phase 3 contextual baselines")
    parser.add_argument("--input", default="data/generated/person_day_features.csv")
    parser.add_argument("--output", default="data/generated/person_day_features.csv")
    parser.add_argument("--minimum-personal-history", type=int, default=14)
    parser.add_argument("--minimum-cohort-size", type=int, default=10)
    parser.add_argument("--minimum-operational-size", type=int, default=10)
    args = parser.parse_args()

    cfg = BaselineConfig(
        minimum_personal_history_days=args.minimum_personal_history,
        minimum_cohort_size=args.minimum_cohort_size,
        minimum_operational_size=args.minimum_operational_size,
    )
    df = pd.read_csv(args.input)
    engineer = BaselineEngineer(cfg)
    out = engineer.build_features(df)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output, index=False)

    report = {
        "rows": int(len(out)),
        "columns": int(len(out.columns)),
        "new_columns": int(len(out.columns) - len(df.columns)),
        "date_min": str(out["date"].min()),
        "date_max": str(out["date"].max()),
        "config": engineer.config_dict(),
        "forbidden_columns_present": [],
    }
    report_path = output.parent / "baseline_generation_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Person-day rows: {len(out):,}")
    print(f"Input features: {len(df.columns):,}")
    print(f"Output features: {len(out.columns):,}")
    print(f"New baseline/context features: {len(out.columns) - len(df.columns):,}")
    print(f"Date range: {out['date'].min()} → {out['date'].max()}")
    print(f"Wrote: {output}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
