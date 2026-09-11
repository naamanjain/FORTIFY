from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.ml.intervention_policy import validate_intervention_output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate FORTIFY Phase 6 intervention recommendations.")
    parser.add_argument("--input", default="data/generated/intervention_recommendations.csv")
    parser.add_argument("--report", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    frame = pd.read_csv(Path(args.input))
    validate_intervention_output(frame)
    if args.report:
        report = json.loads(Path(args.report).read_text(encoding="utf-8"))
        if report.get("phase") != 6:
            raise ValueError("Report is not a Phase 6 report")
    print(f"VALIDATION PASSED: {len(frame):,} rows, {len(frame.columns):,} columns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
