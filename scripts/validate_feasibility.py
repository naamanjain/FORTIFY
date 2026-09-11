from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.ml.feasibility_engineering import validate_feasibility_output


def main() -> int:
    p = argparse.ArgumentParser(description="Validate FORTIFY Phase 7 feasibility output.")
    p.add_argument("--input", default="data/generated/intervention_feasibility.csv")
    p.add_argument("--expected-rows", type=int, default=None)
    p.add_argument("--phase6-input", default="data/generated/intervention_recommendations.csv")
    args = p.parse_args()
    frame = pd.read_csv(ROOT / args.input)
    validate_feasibility_output(frame)
    if args.expected_rows is not None and len(frame) != args.expected_rows:
        raise ValueError(f"Expected {args.expected_rows} rows, found {len(frame)}")
    phase6 = pd.read_csv(ROOT / args.phase6_input)
    if not frame[["person_id", "date"]].equals(phase6[["person_id", "date"]]):
        raise ValueError("Phase 7 person/date grain does not match Phase 6 input")
    print(f"VALIDATION PASSED: {len(frame):,} rows, {len(frame.columns):,} columns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
