from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for path in (ROOT, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

EXPECTED_ROWS = 90_000
FORBIDDEN = {
    "mood_score", "energy_score", "sleep_quality", "perceived_stress",
    "workload_manageability", "support_request",
}
ALLOWED_BANDS = {"LOW", "MODERATE", "HIGH"}
ALLOWED_FEASIBILITY = {"FEASIBLE", "FEASIBLE_WITH_ADJUSTMENT", "CONSTRAINED", "NOT_FEASIBLE"}


def fail(message: str) -> None:
    raise SystemExit(f"VALIDATION FAILED: {message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 12 demonstration artifacts")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    root = Path(args.root).resolve()
    generated = root / "data" / "generated"
    phase12 = root / "artifacts" / "phase12"

    for filename, required in {
        "risk_decisions.csv": {"person_id", "date", "welfare_risk_probability", "risk_band"},
        "intervention_recommendations.csv": {"person_id", "date", "recommended_action", "priority", "risk_band"},
        "intervention_feasibility.csv": {"person_id", "date", "recommended_action", "feasibility_status"},
    }.items():
        path = generated / filename
        if not path.exists(): fail(f"missing {path}")
        df = pd.read_csv(path)
        if len(df) != EXPECTED_ROWS: fail(f"{filename} row count {len(df)} != {EXPECTED_ROWS}")
        if required - set(df.columns): fail(f"{filename} missing {sorted(required - set(df.columns))}")
        if FORBIDDEN & set(df.columns): fail(f"{filename} exposes raw wellness fields")
        if df[["person_id", "date"]].duplicated().any(): fail(f"{filename} duplicate person/date rows")

    manifest = phase12 / "demo_manifest.json"
    timeline_path = phase12 / "demo_case_timeline.csv"
    report = phase12 / "demo_readiness_report.json"
    for p in (manifest, timeline_path, report):
        if not p.exists(): fail(f"missing {p}")

    m = json.loads(manifest.read_text(encoding="utf-8"))
    hero = m["hero_case"]
    if hero["risk_band"] not in ALLOWED_BANDS: fail("invalid hero risk band")
    if hero["feasibility_status"] not in ALLOWED_FEASIBILITY: fail("invalid hero feasibility status")
    if hero["recommended_action"] in {"DISCIPLINARY_ACTION", "PUNISHMENT", "TERMINATION"}: fail("forbidden action in manifest")
    if m.get("raw_wellness_in_outputs") is not False: fail("manifest privacy flag")

    timeline = pd.read_csv(timeline_path)
    if timeline.empty: fail("hero timeline empty")
    if len(timeline) > 22 or len(timeline) < 2: fail("unexpected hero timeline size")
    if timeline[["person_id", "date"]].duplicated().any(): fail("hero timeline duplicate person/date")
    if set(timeline["risk_band"]).difference(ALLOWED_BANDS): fail("invalid timeline risk band")
    if set(timeline["feasibility_status"]).difference(ALLOWED_FEASIBILITY): fail("invalid timeline feasibility state")
    if FORBIDDEN & set(timeline.columns): fail("hero timeline exposes raw wellness fields")
    if timeline["person_id"].nunique() != 1: fail("hero timeline contains multiple personnel")

    # Selection is evidence-based: hero must end in the intended high-priority constrained/adjusted state.
    last = timeline.sort_values("date").iloc[-1]
    if last["risk_band"] != "HIGH": fail("hero does not end HIGH")
    if last["recommended_action"] != "PRIORITY_WELFARE_REVIEW": fail("hero action is not priority welfare review")
    if last["feasibility_status"] not in {"CONSTRAINED", "FEASIBLE_WITH_ADJUSTMENT"}: fail("hero does not demonstrate a constraint")

    print("PHASE 12 DEMO VALIDATION PASSED")
    print(json.dumps({
        "source_rows": EXPECTED_ROWS,
        "source_personnel": 500,
        "hero_person_id": hero["person_id"],
        "hero_date": hero["target_date"],
        "timeline_rows": len(timeline),
        "privacy": "PASS",
        "deterministic_manifest": True,
        "synthetic_data": True,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
