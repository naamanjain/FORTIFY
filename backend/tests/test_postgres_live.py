"""Live PostgreSQL integration checks (disposable database only).

Set ``FORTIFY_TEST_POSTGRES_URL`` to a **throwaway** PostgreSQL database. The
fixture drops and recreates the ``public`` schema, so never point this at data
you care about. The default test run skips the module: no server is required to
run the SQLite suite.

The CI job ``postgres-integration`` starts a fresh ``postgres:16`` service and
runs this file. It proves the claims the application makes about PostgreSQL:
schema creation through the versioned migration runner, the partial unique
index used for feedback idempotency, a real workflow transition, and row-lock
serialization between two concurrent writers.
"""
from __future__ import annotations

import os
import secrets
import threading
from pathlib import Path

import pytest

PG_URL = os.getenv("FORTIFY_TEST_POSTGRES_URL", "").strip()
if PG_URL:
    # app.core.config reads this at import time; setting it here keeps the
    # connection layer pointed at the disposable database for the whole module.
    os.environ["FORTIFY_DATABASE_URL"] = PG_URL

pytestmark = pytest.mark.skipif(
    not PG_URL,
    reason="set FORTIFY_TEST_POSTGRES_URL to a disposable PostgreSQL URL",
)

from app.core import database  # noqa: E402
from app.security.rbac import UnitScope  # noqa: E402
from app.services import workflow  # noqa: E402


@pytest.fixture()
def pg(tmp_path: Path, monkeypatch):
    psycopg = pytest.importorskip("psycopg")
    assert database.is_postgres(), "FORTIFY_DATABASE_URL was not a PostgreSQL URL at import"
    with psycopg.connect(PG_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")

    monkeypatch.setenv("FORTIFY_AUDIT_HMAC_KEY", secrets.token_hex(32))
    monkeypatch.setattr(workflow, "AUDIT_PATH", tmp_path / "audit.jsonl")
    # The transition path normally materializes the demo queue first; this
    # module tests the database/store contract, not the generated dataset.
    monkeypatch.setattr(workflow, "ensure_workflow_items", lambda: None)
    monkeypatch.setattr(workflow, "_MATERIALIZED_GUARD", None)
    database.close_postgres_pool()
    yield
    database.close_postgres_pool()


def _seed_item() -> None:
    with database.connect() as conn:
        conn.execute(
            """INSERT INTO workflow_items
               (workflow_item_id, person_id, recommendation_date, risk_band,
                recommended_action, priority, feasibility_status, constraint_flags,
                rationale, requires_human_review, model_version, policy_version,
                feasibility_policy_version, workflow_state, unit_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("WF-PG-TEST", "P-9999", "2026-01-01", "HIGH",
             "PRIORITY_WELFARE_REVIEW", "HIGH", "CONSTRAINED", "",
             "postgres integration fixture", 1, "test-model", "test-policy",
             "test-feasibility-policy", "NEW", "U-001"),
        )


def _transition(new_state: str, *, expected_state: str | None = "NEW") -> dict:
    return workflow.transition_item(
        "WF-PG-TEST",
        new_state=new_state,
        actor_role="WELFARE_OFFICER",
        purpose="WELFARE_SUPPORT",
        reason_code="postgres live integration test",
        expected_state=expected_state,
        unit_scope=UnitScope.script(),
    )


def test_schema_migrations_and_partial_unique_index(pg) -> None:
    workflow.initialize_workflow_store()

    with database.connect() as conn:
        tables = {
            row["table_name"]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )
        }
        assert {
            "workflow_items", "workflow_audit_events", "workflow_support_events",
            "workflow_feedback", "workflow_followups", "schema_migrations",
            "system_metadata",
        } <= tables

        indexes = {
            row["indexname"]
            for row in conn.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
            )
        }
        assert "uq_workflow_feedback_event" in indexes
        assert "uq_workflow_feedback_idem" in indexes
        assert "idx_workflow_items_pending" in indexes

        versions = [row["version"] for row in conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version")]
        assert versions == [1]

        from app.core.migrations import run_migrations
        assert run_migrations(conn) == [], "re-running migrations must be a no-op"


def test_transition_runs_against_postgres(pg) -> None:
    workflow.initialize_workflow_store()
    _seed_item()

    item = _transition("ACKNOWLEDGED")
    assert item["workflow_state"] == "ACKNOWLEDGED"
    assert item["last_actor_role"] == "WELFARE_OFFICER"

    with database.connect() as conn:
        event = conn.execute(
            "SELECT previous_state, new_state FROM workflow_audit_events "
            "WHERE workflow_item_id = ?", ("WF-PG-TEST",)
        ).fetchone()
        assert event is not None
        assert (event["previous_state"], event["new_state"]) == ("NEW", "ACKNOWLEDGED")


def test_concurrent_transitions_serialize_on_row_lock(pg) -> None:
    workflow.initialize_workflow_store()
    _seed_item()

    barrier = threading.Barrier(2)
    outcomes: list[tuple[str, str]] = []

    def attempt(target: str) -> None:
        barrier.wait()
        try:
            _transition(target)
            outcomes.append(("ok", target))
        except Exception as exc:  # noqa: BLE001 - the loser's exact error is asserted below
            outcomes.append(("error", type(exc).__name__))

    threads = [threading.Thread(target=attempt, args=(state,))
               for state in ("ACKNOWLEDGED", "DISMISSED")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    winners = [outcome for outcome in outcomes if outcome[0] == "ok"]
    losers = [outcome for outcome in outcomes if outcome[0] == "error"]
    assert len(winners) == 1, outcomes
    assert len(losers) == 1, outcomes
    assert losers[0][1] == "ValueError", outcomes

    with database.connect() as conn:
        row = conn.execute(
            "SELECT workflow_state FROM workflow_items WHERE workflow_item_id = ?",
            ("WF-PG-TEST",),
        ).fetchone()
        assert row["workflow_state"] == winners[0][1]
        events = conn.execute(
            "SELECT COUNT(*) FROM workflow_audit_events WHERE workflow_item_id = ?",
            ("WF-PG-TEST",),
        ).fetchone()[0]
        assert events == 1, "a lost update wrote a second transition event"
