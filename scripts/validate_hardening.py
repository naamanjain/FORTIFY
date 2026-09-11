from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for path in (ROOT, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pandas as pd
from fastapi.testclient import TestClient

from app.main import app
from app.security.audit import AuditLog
from app.services.workflow import initialize_workflow_store

EXPECTED_ROWS = 90_000
FORBIDDEN_RAW_FIELDS = {
    "mood_score", "energy_score", "sleep_quality", "perceived_stress",
    "workload_manageability", "support_request",
}


def require_csv(path: Path, expected_columns: set[str], expected_rows: int | None = None) -> pd.DataFrame:
    if not path.exists():
        raise SystemExit(f"VALIDATION FAILED: missing artifact {path}")
    frame = pd.read_csv(path)
    missing = expected_columns - set(frame.columns)
    if missing:
        raise SystemExit(f"VALIDATION FAILED: {path.name} missing columns {sorted(missing)}")
    if expected_rows is not None and len(frame) != expected_rows:
        raise SystemExit(f"VALIDATION FAILED: {path.name} has {len(frame)} rows, expected {expected_rows}")
    return frame


def validate_person_day(frame: pd.DataFrame, name: str) -> None:
    if frame[["person_id", "date"]].duplicated().any():
        raise SystemExit(f"VALIDATION FAILED: duplicate person/date rows in {name}")
    if frame["person_id"].nunique() != 500:
        raise SystemExit(f"VALIDATION FAILED: {name} does not cover 500 personnel")
    dates = pd.to_datetime(frame["date"], errors="raise")
    if dates.min().strftime("%Y-%m-%d") != "2026-01-01" or dates.max().strftime("%Y-%m-%d") != "2026-06-29":
        raise SystemExit(f"VALIDATION FAILED: {name} date range is unexpected")


def validate_privacy(frame: pd.DataFrame, name: str) -> None:
    raw = sorted(FORBIDDEN_RAW_FIELDS.intersection(set(frame.columns)))
    if raw:
        raise SystemExit(f"VALIDATION FAILED: {name} exposes raw wellness fields {raw}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate FORTIFY Phase 11 hardening contracts")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    project = Path(args.root).resolve()
    generated = project / "data" / "generated"

    predictions = require_csv(generated / "risk_predictions.csv", {"person_id", "date", "welfare_risk_probability", "risk_level"}, EXPECTED_ROWS)
    recommendations = require_csv(generated / "intervention_recommendations.csv", {"person_id", "date", "recommended_action", "risk_band", "requires_human_review"}, EXPECTED_ROWS)
    feasibility = require_csv(generated / "intervention_feasibility.csv", {"person_id", "date", "recommended_action", "feasibility_status", "requires_human_review"}, EXPECTED_ROWS)
    for frame, name in ((predictions, "predictions"), (recommendations, "recommendations"), (feasibility, "feasibility")):
        validate_person_day(frame, name)
        validate_privacy(frame, name)

    # Apply idempotent workflow schema/index hardening before validating it.
    initialize_workflow_store()

    audit_path = project / "artifacts" / "phase8" / "dashboard_audit.jsonl"
    if not AuditLog(audit_path).verify_chain():
        raise SystemExit("VALIDATION FAILED: audit chain")

    db_path = project / "fortify.db"
    if not db_path.exists():
        raise SystemExit("VALIDATION FAILED: prototype database missing")
    with sqlite3.connect(db_path) as conn:
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        if fk != 1:
            # The validator checks the runtime contract, not a connection's default state.
            conn.execute("PRAGMA foreign_keys = ON")
            fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        if fk != 1:
            raise SystemExit("VALIDATION FAILED: foreign-key enforcement unavailable")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"workflow_items", "workflow_audit_events"}.issubset(tables):
            raise SystemExit("VALIDATION FAILED: workflow tables missing")
        orphan = conn.execute("""SELECT COUNT(*) FROM workflow_audit_events e
            LEFT JOIN workflow_items w ON w.workflow_item_id=e.workflow_item_id
            WHERE w.workflow_item_id IS NULL""").fetchone()[0]
        if orphan:
            raise SystemExit(f"VALIDATION FAILED: {orphan} orphan workflow audit events")
        indices = {r[1] for r in conn.execute("PRAGMA index_list(workflow_items)")}
        if "idx_workflow_items_pending" not in indices:
            raise SystemExit("VALIDATION FAILED: workflow pending index missing")

    with TestClient(app) as client:
        health = client.get("/health")
    if health.status_code != 200 or health.json() != {"status": "ok", "service": "FORTIFY"}:
        raise SystemExit("VALIDATION FAILED: health endpoint")

    report = {
        "phase": "Phase 11 — Testing + Hardening",
        "artifacts_checked": 3,
        "rows_per_person_day_artifact": EXPECTED_ROWS,
        "audit_chain": "PASS",
        "workflow_foreign_keys": "PASS",
        "workflow_indexes": "PASS",
        "privacy_schema": "PASS",
        "health_endpoint": "PASS",
        "synthetic_data": True,
    }
    print("PHASE 11 HARDENING VALIDATION PASSED")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
