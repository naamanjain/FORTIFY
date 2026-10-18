"""Versioned schema migrations for the workflow store.

Replaces ad-hoc ``_ensure_column`` calls with an ordered, recorded, idempotent
migration list. Each migration runs exactly once per database (recorded in
``schema_migrations``); re-running initialization is a no-op; new migrations
apply forward. Dialect-neutral SQL only (SQLite and PostgreSQL).

A production deployment that needs richer machinery should move this list to
Alembic wholesale - the versioned list below is intentionally simple, and the
runner refuses to start if a recorded migration is missing from the code (a
database newer than the application is an operator error, not something to
"fix" silently).
"""
from __future__ import annotations

from typing import Any

MIGRATION_VERSION = 1

# Each migration: (version, name, tuple of SQL statements). Statements use the
# shared dialect-neutral SQL of the persistence layer.
MIGRATIONS: list[tuple[int, str, tuple[str, ...]]] = [
    (1, "workflow-store-base", (
        """CREATE TABLE IF NOT EXISTS workflow_items (
            workflow_item_id TEXT PRIMARY KEY, person_id TEXT NOT NULL, recommendation_date TEXT NOT NULL,
            risk_band TEXT NOT NULL, recommended_action TEXT NOT NULL, priority TEXT NOT NULL,
            feasibility_status TEXT NOT NULL, constraint_flags TEXT NOT NULL, rationale TEXT NOT NULL,
            requires_human_review INTEGER NOT NULL, model_version TEXT NOT NULL, policy_version TEXT NOT NULL,
            feasibility_policy_version TEXT NOT NULL, workflow_state TEXT NOT NULL,
            last_transition_at TEXT, last_actor_role TEXT, last_reason_code TEXT)""",
        """CREATE TABLE IF NOT EXISTS workflow_audit_events (
            event_id TEXT PRIMARY KEY, workflow_item_id TEXT NOT NULL, person_id TEXT NOT NULL,
            recommendation_date TEXT NOT NULL, previous_state TEXT NOT NULL, new_state TEXT NOT NULL,
            actor_role TEXT NOT NULL, purpose TEXT NOT NULL, timestamp TEXT NOT NULL, reason_code TEXT NOT NULL,
            model_version TEXT NOT NULL, policy_version TEXT NOT NULL, feasibility_policy_version TEXT NOT NULL,
            workflow_policy_version TEXT NOT NULL,
            FOREIGN KEY (workflow_item_id) REFERENCES workflow_items(workflow_item_id))""",
        """CREATE TABLE IF NOT EXISTS workflow_support_events (
            support_event_id TEXT PRIMARY KEY, workflow_item_id TEXT NOT NULL, person_id TEXT NOT NULL,
            support_action TEXT NOT NULL, completed_at TEXT NOT NULL, actor_role TEXT NOT NULL,
            FOREIGN KEY (workflow_item_id) REFERENCES workflow_items(workflow_item_id))""",
        """CREATE TABLE IF NOT EXISTS workflow_feedback (
            feedback_id TEXT PRIMARY KEY, workflow_item_id TEXT NOT NULL, support_event_id TEXT NOT NULL,
            person_id TEXT NOT NULL, helpfulness INTEGER NOT NULL, comment TEXT,
            follow_up_requested INTEGER NOT NULL, submitted_at TEXT NOT NULL, recorded_by_role TEXT NOT NULL,
            idempotency_key TEXT,
            FOREIGN KEY (workflow_item_id) REFERENCES workflow_items(workflow_item_id),
            FOREIGN KEY (support_event_id) REFERENCES workflow_support_events(support_event_id))""",
        """CREATE TABLE IF NOT EXISTS workflow_followups (
            followup_id TEXT PRIMARY KEY, workflow_item_id TEXT NOT NULL, support_event_id TEXT NOT NULL,
            person_id TEXT NOT NULL, scheduled_for TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL, created_by_role TEXT NOT NULL, last_updated_at TEXT NOT NULL,
            completed_at TEXT, completed_by_role TEXT,
            FOREIGN KEY (workflow_item_id) REFERENCES workflow_items(workflow_item_id),
            FOREIGN KEY (support_event_id) REFERENCES workflow_support_events(support_event_id))""",
        "ALTER TABLE workflow_items ADD COLUMN support_completed_at TEXT",
        "ALTER TABLE workflow_items ADD COLUMN support_completed_by_role TEXT",
        "ALTER TABLE workflow_items ADD COLUMN active_support_event_id TEXT",
        "ALTER TABLE workflow_items ADD COLUMN active_followup_id TEXT",
        "ALTER TABLE workflow_items ADD COLUMN feedback_submitted INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE workflow_items ADD COLUMN unit_id TEXT",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_workflow_feedback_event ON workflow_feedback(workflow_item_id, support_event_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_workflow_feedback_idem ON workflow_feedback(idempotency_key) WHERE idempotency_key IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_workflow_items_pending ON workflow_items(workflow_state, recommendation_date, priority, workflow_item_id)",
        "CREATE INDEX IF NOT EXISTS idx_workflow_audit_item ON workflow_audit_events(workflow_item_id, timestamp, event_id)",
        "CREATE INDEX IF NOT EXISTS idx_workflow_followups_status ON workflow_followups(status, scheduled_for, followup_id)",
        "CREATE INDEX IF NOT EXISTS idx_workflow_feedback_item ON workflow_feedback(workflow_item_id, submitted_at, feedback_id)",
    )),
]


def _table_exists(conn: Any, table: str) -> bool:
    from app.core.database import is_sqlite

    if is_sqlite():
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        return row is not None
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name = ?", (table,)
    ).fetchall()
    return len(rows) > 0


def _applied_versions(conn: Any) -> set[int]:
    if not _table_exists(conn, "schema_migrations"):
        return set()
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {int(row[0]) for row in rows}


def _is_add_column(statement: str) -> bool:
    upper = " ".join(statement.upper().split())
    return upper.startswith("ALTER TABLE ") and " ADD COLUMN " in upper


def _parse_add_column(statement: str) -> tuple[str, str]:
    parts = statement.split()
    table = parts[2]
    column = parts[parts.index("COLUMN", 3) + 1]
    return table, column


def run_migrations(conn: Any) -> list[int]:
    """Apply pending migrations; return the versions applied this call.

    Idempotent: applied versions are skipped; running twice applies nothing.
    Refuses to run when the database has migrations newer than this code.
    """
    applied = _applied_versions(conn)
    unknown = applied - {v for v, _, _ in MIGRATIONS}
    if unknown:
        raise RuntimeError(
            f"Database has migration versions {sorted(unknown)} that this application "
            "does not know. Deploy the matching application version; do not downgrade silently."
        )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    just_applied: list[int] = []
    from datetime import datetime, timezone

    for version, name, statements in sorted(MIGRATIONS):
        if version in applied:
            continue
        for statement in statements:
            # Databases created before the migration runner existed may already
            # carry migration-1 columns; ADD COLUMN statements are therefore
            # guarded by a live column check (CREATE TABLE/INDEX IF NOT EXISTS
            # are naturally idempotent).
            if _is_add_column(statement):
                table, column = _parse_add_column(statement)
                from app.core.database import column_exists

                if column_exists(conn, table, column):
                    continue
            try:
                conn.execute(statement)
            except Exception as exc:  # noqa: BLE001 - translate to actionable failure
                # Column-add migrations are not idempotent by nature; a failure
                # here means the recorded state and the schema disagree.
                raise RuntimeError(
                    f"Migration {version} ({name}) failed: {exc}. "
                    "The schema may be partially migrated; inspect before retrying."
                ) from exc
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (version, name, datetime.now(timezone.utc).isoformat()),
        )
        just_applied.append(version)
    # Schema changes are durable immediately: the runner commits its own work
    # so a partially-used connection elsewhere cannot roll it back.
    if just_applied:
        conn.commit()
    return just_applied