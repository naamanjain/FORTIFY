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

from app.services.workflow import _db_path, ensure_workflow_items  # type: ignore

EXPECTED_ROWS = 90_000
START = "2026-01-01"
END = "2026-06-29"
FORBIDDEN = {
    "mood_score", "energy_score", "sleep_quality", "perceived_stress",
    "workload_manageability", "support_request",
}


def load(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="raise")
    return df


def open_workflow_cases(db_path: Path) -> dict[tuple[str, str], str]:
    """Cases that exist in the workflow store AND still expect a human decision."""
    import sqlite3
    from app.services.workflow import PENDING_STATES
    # A fresh clone has an empty schema until the first caller materializes the
    # alert-policy cases from review_queue.csv. Without this the lookup sees an
    # empty store and the hero selection fails on a clean pipeline run.
    ensure_workflow_items()
    placeholders = ",".join("?" for _ in PENDING_STATES)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT person_id, recommendation_date, workflow_state FROM workflow_items"
            f" WHERE workflow_state IN ({placeholders})",
            PENDING_STATES,
        ).fetchall()
    return {(str(pid), str(day)): str(state) for pid, day, state in rows}


def choose_hero(merged: pd.DataFrame, open_cases: dict[tuple[str, str], str]) -> tuple[str, pd.Timestamp, float]:
    """Pick the demonstration case among cases a welfare officer can really open.

    The hero used to be chosen from the scoring outputs alone, which regularly
    selected a person-day the alert policy never turned into a workflow case -
    so the scripted demo step "open the prepared hero case" landed on a profile
    with no case, and the missing row was reported as state NEW.
    """
    candidates = []
    for person_id, g in merged.groupby("person_id", sort=True):
        g = g.sort_values("date").reset_index(drop=True)
        g["prior_21d_probability"] = g["welfare_risk_probability"].shift(21)
        c = g[(g["risk_band"] == "HIGH") &
              (g["recommended_action"] == "PRIORITY_WELFARE_REVIEW") &
              (g["feasibility_status"].isin(["CONSTRAINED", "FEASIBLE_WITH_ADJUSTMENT"])) &
              g["prior_21d_probability"].notna()]
        for _, row in c.iterrows():
            delta = float(row["welfare_risk_probability"] - row["prior_21d_probability"])
            flags = [x.strip() for x in str(row["constraint_flags"]).split("|") if x.strip()]
            key = (str(person_id), row["date"].strftime("%Y-%m-%d"))
            if delta > 0 and len(flags) >= 2 and key in open_cases:
                candidates.append((delta, str(person_id), row["date"]))
    if not candidates:
        raise ValueError(
            "No open workflow case satisfies the Phase 12 demo criteria; the review "
            "queue and the demonstration script have diverged. Run build_review_queue.py "
            "and do not ship a hero case that no officer can open."
        )
    delta, person_id, date = max(candidates, key=lambda x: (x[0], x[1], x[2]))
    return person_id, pd.Timestamp(date), delta


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare deterministic FORTIFY Phase 12 demonstration artifacts")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    out = Path(args.output_dir).resolve() if args.output_dir else root / "artifacts" / "phase12"
    out.mkdir(parents=True, exist_ok=True)
    generated = root / "data" / "generated"

    predictions = load(generated / "risk_decisions.csv")
    recs = load(generated / "intervention_recommendations.csv")
    feas = load(generated / "intervention_feasibility.csv")
    for name, df in (("risk_decisions", predictions), ("intervention_recommendations", recs), ("intervention_feasibility", feas)):
        if len(df) != EXPECTED_ROWS:
            raise ValueError(f"{name}: expected {EXPECTED_ROWS} rows, found {len(df)}")
        if FORBIDDEN & set(df.columns):
            raise ValueError(f"{name}: raw wellness fields exposed")

    merged = predictions.merge(recs, on=["person_id", "date"], suffixes=("", "_recommendation"), validate="one_to_one")
    merged = merged.merge(feas, on=["person_id", "date", "recommended_action"], suffixes=("", "_feasibility"), validate="one_to_one")

    db_path = _db_path()
    open_cases = open_workflow_cases(db_path)
    person_id, target_date, delta = choose_hero(merged, open_cases)
    hero = merged[(merged.person_id == person_id) & (merged.date.between(target_date - pd.Timedelta(days=21), target_date))].sort_values("date").copy()

    day_key = target_date.strftime("%Y-%m-%d")
    workflow_state = open_cases[(person_id, day_key)]

    timeline_cols = [
        "person_id", "date", "welfare_risk_probability", "risk_band", "recommended_action",
        "priority", "feasibility_status", "constraint_flags", "workflow_state",
    ]
    hero["workflow_state"] = workflow_state
    timeline = hero[timeline_cols].copy()
    timeline["date"] = timeline["date"].dt.strftime("%Y-%m-%d")
    timeline_path = out / "demo_case_timeline.csv"
    timeline.to_csv(timeline_path, index=False)

    target = merged[(merged.person_id == person_id) & (merged.date == target_date)].iloc[0]
    hero_manifest = {
        "phase": "Phase 12 — Final Demonstration Preparation",
        "synthetic_demo_only": True,
        "selection_policy": "Largest 21-day increase in model probability ending HIGH with PRIORITY_WELFARE_REVIEW and at least two feasibility constraint flags; deterministic tie-breakers by person_id/date.",
        "hero_case": {
            "person_id": person_id,
            "target_date": target_date.strftime("%Y-%m-%d"),
            "probability": round(float(target["welfare_risk_probability"]), 6),
            "risk_band": str(target["risk_band"]),
            "recommended_action": str(target["recommended_action"]),
            "priority": str(target["priority"]),
            "feasibility_status": str(target["feasibility_status"]),
            "constraint_flags": [x.strip() for x in str(target["constraint_flags"]).split("|") if x.strip()],
            "workflow_state_at_preparation": workflow_state,
            "risk_probability_increase_over_21_days": round(delta, 6),
        },
        "demo_flow": [
            "Observe recent person-day risk trajectory.",
            "Contextualize the target day using existing operational contributing signals and feasibility constraints.",
            "Show the Phase 5 welfare-risk probability and LOW/MODERATE/HIGH interpretation.",
            "Show the Phase 6 welfare-support recommendation and Phase 7 feasibility result.",
            "Use the Phase 10 workflow panel to acknowledge and review the recommendation as an authorized human operator.",
            "Record supported workflow transitions and show the audit/history indicator.",
        ],
        "safety_boundary": "Operational/welfare decision support only; synthetic demonstration data; no medical diagnosis, disciplinary action, or autonomous personnel action.",
        "raw_wellness_in_outputs": False,
    }
    manifest_path = out / "demo_manifest.json"
    manifest_path.write_text(json.dumps(hero_manifest, indent=2) + "\n", encoding="utf-8")

    report = {
        "phase": "Phase 12 — Final Demonstration Preparation",
        "status": "PASS",
        "source_rows": EXPECTED_ROWS,
        "source_personnel": int(merged["person_id"].nunique()),
        "date_range": [merged["date"].min().strftime("%Y-%m-%d"), merged["date"].max().strftime("%Y-%m-%d")],
        "hero_case": {"person_id": person_id, "date": target_date.strftime("%Y-%m-%d")},
        "timeline_rows": int(len(timeline)),
        "artifacts": ["demo_case_timeline.csv", "demo_manifest.json", "demo_readiness_report.json"],
        "privacy_check": "PASS",
        "deterministic_selection": True,
        "workflow_state_mutated": False,
        "synthetic_data": True,
    }
    (out / "demo_readiness_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print("PHASE 12 DEMO PREPARATION PASSED")
    print(f"Source rows: {EXPECTED_ROWS}")
    print(f"Personnel: {merged['person_id'].nunique()}")
    print(f"Hero case: {person_id} on {target_date:%Y-%m-%d}")
    print(f"Timeline rows: {len(timeline)}")
    print(f"Workflow state at preparation: {workflow_state}")
    print(f"Artifacts: {timeline_path.name}, demo_manifest.json, demo_readiness_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
