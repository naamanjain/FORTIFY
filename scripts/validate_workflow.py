from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for path in (ROOT, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.security.audit import AuditLog
from app.services.workflow import ALLOWED_ACTIONS, WORKFLOW_STATES, _db_path, ensure_workflow_items


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate FORTIFY Phase 10 workflow state and audit structures")
    parser.add_argument("--database", default=None, help="Optional SQLite database path")
    args = parser.parse_args()

    ensure_workflow_items()
    db = Path(args.database) if args.database else _db_path()
    if not db.exists():
        raise SystemExit(f"Database not found: {db}")
    with sqlite3.connect(db) as conn:
        workflow_count = conn.execute("SELECT COUNT(*) FROM workflow_items").fetchone()[0]
        unique_people = conn.execute("SELECT COUNT(DISTINCT person_id) FROM workflow_items").fetchone()[0]
        duplicate = conn.execute("SELECT COUNT(*) FROM (SELECT person_id, recommendation_date, COUNT(*) c FROM workflow_items GROUP BY person_id, recommendation_date HAVING c > 1)").fetchone()[0]
        invalid_state = conn.execute("SELECT COUNT(*) FROM workflow_items WHERE workflow_state NOT IN (?, ?, ?, ?, ?, ?, ?)", tuple(sorted(WORKFLOW_STATES))).fetchone()[0]
        invalid_action = conn.execute("SELECT COUNT(*) FROM workflow_items WHERE recommended_action NOT IN (?, ?, ?, ?, ?, ?, ?)", tuple(sorted(ALLOWED_ACTIONS))).fetchone()[0]
        raw_wellness_columns = [r[1] for r in conn.execute("PRAGMA table_info(workflow_items)") if any(x in r[1].lower() for x in ["mood", "energy", "sleep_quality", "perceived_stress", "support_request"])]
        audit_count = conn.execute("SELECT COUNT(*) FROM workflow_audit_events").fetchone()[0]
    audit = AuditLog(ROOT / "artifacts" / "phase8" / "dashboard_audit.jsonl")
    if duplicate or invalid_state or invalid_action or raw_wellness_columns:
        raise SystemExit("VALIDATION FAILED")
    if not audit.verify_chain():
        raise SystemExit("VALIDATION FAILED: audit hash chain")
    print("PHASE 10 WORKFLOW VALIDATION PASSED")
    print(f"Workflow rows: {workflow_count}")
    print(f"Unique personnel: {unique_people}")
    print(f"Audit workflow events: {audit_count}")
    print("Person/date/action uniqueness: PASS")
    print("Workflow state vocabulary: PASS")
    print("Safety/privacy schema check: PASS")
    print("Audit hash chain: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
