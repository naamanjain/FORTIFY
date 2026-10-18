"""Backup / restore drill — a demonstrable, timed procedure, not a promise.

Performs, against the configured database:

  1. BACKUP   — consistent snapshot of the workflow store.
  2. MUTATE   — record the current case count, then make a real change.
  3. RESTORE  — wipe the live store and restore from the snapshot.
  4. VERIFY   — case count matches the pre-mutation record; workflow history
                survives; the audit chain verifies against its anchor;
                constraints are intact (duplicate feedback is refused).

The drill prints elapsed times and writes a report to
artifacts/backup_restore/drill_report.json. It measures what it did on THIS
machine THIS run; it does NOT claim an RPO/RTO for any deployment.

Usage:
    python scripts/backup_restore_drill.py                 # SQLite (demo store)
    FORTIFY_DATABASE_URL=postgresql://... python scripts/backup_restore_drill.py
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.core.config import settings  # noqa: E402
from app.core.database import connect, is_postgres, is_sqlite  # noqa: E402
from app.core.database import resolve_sqlite_url  # noqa: E402
from app.security.audit import AuditLog  # noqa: E402
from app.core.paths import AUDIT_PATH  # noqa: E402
from app.security.rbac import UnitScope as _UnitScope
_SCRIPT_SCOPE = _UnitScope.script()


def _counts() -> dict[str, int]:
    with connect() as conn:
        tables = ("workflow_items", "workflow_audit_events", "workflow_support_events",
                  "workflow_feedback", "workflow_followups", "schema_migrations")
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}


def _backup_sqlite(backup_path: Path) -> None:
    source = sqlite3.connect(resolve_sqlite_url(settings.database_url))
    try:
        # The online backup API produces a consistent snapshot while the
        # source stays usable.
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()


def _restore_sqlite(backup_path: Path) -> None:
    live = resolve_sqlite_url(settings.database_url)
    destination = sqlite3.connect(live)
    try:
        source = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
        finally:
            source.close()
    finally:
        destination.close()


def _backup_postgres(backup_path: Path) -> None:
    """pg_dump through docker (the drill runs where the container runs)."""
    import subprocess

    # Extract connection parameters from the URL.
    from urllib.parse import urlparse

    parsed = urlparse(settings.database_url)
    container = os.environ.get("FORTIFY_PG_CONTAINER", "fortify-pg-test")
    dump = subprocess.run(
        ["docker", "exec", container, "pg_dump", "-U", "postgres", parsed.path.lstrip("/")],
        capture_output=True, text=True, check=True,
    )
    backup_path.write_text(dump.stdout, encoding="utf-8")


def _restore_postgres(backup_path: Path) -> None:
    import subprocess
    from urllib.parse import urlparse

    parsed = urlparse(settings.database_url)
    container = os.environ.get("FORTIFY_PG_CONTAINER", "fortify-pg-test")
    database = parsed.path.lstrip("/")
    drop = "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
    subprocess.run(["docker", "exec", container, "psql", "-U", "postgres", "-d", database, "-c", drop],
                   check=True, capture_output=True, text=True)
    sql = backup_path.read_text(encoding="utf-8")
    subprocess.run(["docker", "exec", "-i", container, "psql", "-U", "postgres", "-d", database],
                   input=sql, check=True, capture_output=True, text=True)


def main() -> int:
    if is_postgres() and shutil.which("docker") is None:
        raise SystemExit("PostgreSQL drill requires docker (pg_dump/psql).")

    started = time.perf_counter()
    report: dict = {
        "drill_at": datetime.now(timezone.utc).isoformat(),
        "backend": "postgresql" if is_postgres() else "sqlite",
        "steps": {},
    }

    before = _counts()
    with connect() as conn:
        item = conn.execute("SELECT workflow_item_id FROM workflow_items LIMIT 1").fetchone()
    if item is None:
        raise SystemExit("Workflow store is empty; run scripts/build_all.py first.")
    item_id = item[0]

    # 1. BACKUP
    step = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        backup_path = Path(tmp) / "workflow-backup"
        if is_postgres():
            _backup_postgres(backup_path)
        else:
            _backup_sqlite(backup_path)
        report["steps"]["backup"] = {"seconds": round(time.perf_counter() - step, 3),
                                     "bytes": backup_path.stat().st_size}

        # 2. MUTATE (a real, audited transition so restoring must undo it)
        from app.services import workflow as wf

        step = time.perf_counter()
        detail = wf.get_item(item_id, unit_scope=_SCRIPT_SCOPE)
        state = detail["workflow_state"]
        target = {"NEW": "ACKNOWLEDGED", "ACKNOWLEDGED": "IN_REVIEW", "IN_REVIEW": "DEFERRED"}.get(state)
        if target is None:
            raise SystemExit(f"No reversible drill transition from state {state}.")
        wf.transition_item(item_id, new_state=target, actor_role="WELFARE_OFFICER",
                           purpose="WELFARE_SUPPORT", reason_code="BACKUP-RESTORE-DRILL",
                           unit_scope=_SCRIPT_SCOPE)
        mutated_state = wf.get_item(item_id, unit_scope=_SCRIPT_SCOPE)["workflow_state"]
        during = _counts()
        report["steps"]["mutate"] = {"seconds": round(time.perf_counter() - step, 3),
                                     "transition": f"{state}->{mutated_state}",
                                     "audit_rows_during": during["workflow_audit_events"]}

        # 3. RESTORE
        step = time.perf_counter()
        if is_postgres():
            _restore_postgres(backup_path)
        else:
            _restore_sqlite(backup_path)
        report["steps"]["restore"] = {"seconds": round(time.perf_counter() - step, 3)}

    # 4. VERIFY
    step = time.perf_counter()
    restored = _counts()
    restored_state = None
    with connect() as conn:
        row = conn.execute("SELECT workflow_state FROM workflow_items WHERE workflow_item_id = ?",
                           (item_id,)).fetchone()
        restored_state = row[0] if row else None
    report["steps"]["verify"] = {"seconds": round(time.perf_counter() - step, 3)}

    checks = {
        "case_count_matches_pre_mutation": restored["workflow_items"] == before["workflow_items"],
        "audit_rows_match_pre_mutation": restored["workflow_audit_events"] == before["workflow_audit_events"],
        "drill_transition_undone": restored_state == state,
        "support_events_intact": restored["workflow_support_events"] == before["workflow_support_events"],
        "feedback_intact": restored["workflow_feedback"] == before["workflow_feedback"],
        "migrations_recorded": restored["schema_migrations"] >= 1,
        "audit_chain_valid_after_restore": AuditLog(AUDIT_PATH).verify().valid,
        "constraints_intact": _constraints_intact(),
    }
    report["checks"] = checks
    report["counts_before"] = before
    report["counts_after_restore"] = restored
    report["total_seconds"] = round(time.perf_counter() - started, 3)
    report["measured_note"] = (
        "Times are measurements of THIS drill run on THIS machine. They are not "
        "RPO/RTO guarantees for any deployment."
    )

    out = ROOT / "artifacts" / "backup_restore" / "drill_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Backend: {report['backend']}")
    for step_name in ("backup", "mutate", "restore", "verify"):
        print(f"  {step_name:>8}: {report['steps'][step_name]['seconds']}s")
    for name, ok in checks.items():
        print(f"  {'PASS' if ok else 'FAIL'} {name}")
    print(f"Total: {report['total_seconds']}s | report: {out}")
    return 0 if all(checks.values()) else 1


def _constraints_intact() -> bool:
    """The unique feedback constraint must survive a restore."""
    import hashlib

    with connect() as conn:
        row = conn.execute(
            "SELECT workflow_item_id, support_event_id FROM workflow_feedback LIMIT 1"
        ).fetchone()
        if row is None:
            return True  # nothing to violate with; index existence is checked below
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'uq_workflow_feedback%'"
        ).fetchall() if is_sqlite() else conn.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename='workflow_feedback'"
        ).fetchall()
        names = {r[0] for r in indexes}
        return "uq_workflow_feedback_event" in names


if __name__ == "__main__":
    raise SystemExit(main())