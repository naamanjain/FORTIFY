"""Regenerate the complete FORTIFY demonstration environment.

Runs the deterministic pipeline end to end with fixed defaults (seed 42,
500 personnel, 180 days). A fresh clone needs exactly this command before
the backend can serve dashboard data:

    python scripts/build_all.py

Steps: synthetic events -> person-day features -> personal/cohort baselines
-> model training -> calibrated risk decisions -> intervention policy ->
feasibility -> demo manifest. Every step is seeded and reproducible.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STEPS = [
    "generate_synthetic_data.py",
    "build_features.py",
    "build_baselines.py",
    "train_model.py",
    "build_phase5_risk_layer.py",
    "build_review_queue.py",
    "build_interventions.py",
    "build_feasibility.py",
    "prepare_demo.py",
]


def main() -> int:
    print("FORTIFY demo pipeline — deterministic regeneration (seed 42, 500 personnel, 180 days)")
    started = time.time()
    for name in STEPS:
        step_started = time.time()
        print(f"\n=== {name} ===", flush=True)
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / name)], cwd=str(ROOT))
        if result.returncode != 0:
            print(f"PIPELINE FAILED at {name} (exit code {result.returncode})", file=sys.stderr)
            return result.returncode
        print(f"--- {name} finished in {time.time() - step_started:.1f}s ---", flush=True)
    print(f"\nPIPELINE COMPLETE in {time.time() - started:.1f}s")
    print("Next: start the backend (see README) and open the frontend.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
