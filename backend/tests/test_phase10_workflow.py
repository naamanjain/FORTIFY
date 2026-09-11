from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
import app.services.workflow as workflow


HEADERS = {"X-Fortify-Role": "WELFARE_OFFICER", "X-Fortify-Purpose": "WELFARE_SUPPORT"}
AUDITOR_HEADERS = {"X-Fortify-Role": "AUDITOR", "X-Fortify-Purpose": "AUDIT"}


@pytest.fixture()
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "workflow.db"
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(workflow, "_db_path", lambda: db)
    from app.api.routes import workflow as workflow_route
    monkeypatch.setattr(workflow_route, "AUDIT_PATH", audit)
    return db


def first_workflow_id() -> str:
    return workflow._workflow_id("P-0001", "2026-06-29")


def test_workflow_starts_new_and_does_not_auto_complete(isolated_store: Path) -> None:
    with TestClient(main.app) as client:
        response = client.get("/api/workflow/pending?limit=1", headers=HEADERS)
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["workflow_state"] == "NEW"
    assert item["requires_human_review"] is True


def test_valid_transition_creates_audit_event(isolated_store: Path) -> None:
    item_id = first_workflow_id()
    with TestClient(main.app) as client:
        before = client.get(f"/api/workflow/{item_id}", headers=HEADERS)
        response = client.post(f"/api/workflow/{item_id}/transition", headers=HEADERS,
                               json={"new_state": "ACKNOWLEDGED", "reason_code": "ACKNOWLEDGED_FOR_WELFARE_REVIEW"})
        history = client.get(f"/api/workflow/{item_id}/history", headers=HEADERS)
    assert before.status_code == 200
    assert response.status_code == 200
    assert response.json()["workflow_state"] == "ACKNOWLEDGED"
    assert history.status_code == 200
    event = history.json()["events"][-1]
    assert event["previous_state"] == "NEW"
    assert event["new_state"] == "ACKNOWLEDGED"
    assert event["actor_role"] == "WELFARE_OFFICER"
    assert "perceived_stress" not in str(event).lower()


def test_invalid_transition_is_rejected(isolated_store: Path) -> None:
    item_id = first_workflow_id()
    with TestClient(main.app) as client:
        response = client.post(f"/api/workflow/{item_id}/transition", headers=HEADERS,
                               json={"new_state": "COMPLETED", "reason_code": "INVALID_DIRECT_COMPLETION"})
    assert response.status_code == 400


def test_unauthorized_role_and_purpose_are_rejected(isolated_store: Path) -> None:
    item_id = first_workflow_id()
    with TestClient(main.app) as client:
        commander = client.get("/api/workflow/pending", headers={"X-Fortify-Role": "COMMANDER", "X-Fortify-Purpose": "AGGREGATE_OPERATIONS"})
        audit_transition = client.post(f"/api/workflow/{item_id}/transition", headers=AUDITOR_HEADERS,
                                       json={"new_state": "ACKNOWLEDGED", "reason_code": "AUDIT_MUST_NOT_TRANSITION"})
    assert commander.status_code == 403
    assert audit_transition.status_code == 403


def test_auditor_can_read_history_but_not_change_state(isolated_store: Path) -> None:
    item_id = first_workflow_id()
    with TestClient(main.app) as client:
        client.post(f"/api/workflow/{item_id}/transition", headers=HEADERS,
                    json={"new_state": "ACKNOWLEDGED", "reason_code": "ACKNOWLEDGED_FOR_WELFARE_REVIEW"})
        history = client.get(f"/api/workflow/{item_id}/history", headers=AUDITOR_HEADERS)
    assert history.status_code == 200
    assert history.json()["count"] == 1


def test_completed_transition_is_terminal(isolated_store: Path) -> None:
    item_id = first_workflow_id()
    with TestClient(main.app) as client:
        for state, reason in [
            ("ACKNOWLEDGED", "ACKNOWLEDGED_FOR_WELFARE_REVIEW"),
            ("IN_REVIEW", "WELFARE_REVIEW_STARTED"),
            ("SUPPORT_PLANNED", "SUPPORT_PLAN_RECORDED"),
            ("COMPLETED", "SUPPORT_COMPLETED_BY_HUMAN"),
        ]:
            response = client.post(f"/api/workflow/{item_id}/transition", headers=HEADERS,
                                   json={"new_state": state, "reason_code": reason})
            assert response.status_code == 200
        invalid = client.post(f"/api/workflow/{item_id}/transition", headers=HEADERS,
                              json={"new_state": "DEFERRED", "reason_code": "CANNOT_DEFER_COMPLETED"})
    assert invalid.status_code == 400


def test_missing_security_context_rejected(isolated_store: Path) -> None:
    with TestClient(main.app) as client:
        response = client.get("/api/workflow/pending")
    assert response.status_code == 401


def test_workflow_db_contains_no_wellness_columns_or_values(isolated_store: Path) -> None:
    workflow.initialize_workflow_store()
    with sqlite3.connect(isolated_store) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(workflow_items)")]
        audit_columns = [row[1] for row in conn.execute("PRAGMA table_info(workflow_audit_events)")]
    names = " ".join(columns + audit_columns).lower()
    for forbidden in ("mood_score", "energy_score", "sleep_quality", "perceived_stress", "support_request"):
        assert forbidden not in names


def test_audit_chain_remains_valid_after_transition(isolated_store: Path) -> None:
    from app.api.routes import workflow as workflow_route
    item_id = first_workflow_id()
    with TestClient(main.app) as client:
        response = client.post(f"/api/workflow/{item_id}/transition", headers=HEADERS,
                               json={"new_state": "ACKNOWLEDGED", "reason_code": "ACKNOWLEDGED_FOR_WELFARE_REVIEW"})
    assert response.status_code == 200
    from app.security.audit import AuditLog
    assert AuditLog(workflow_route.AUDIT_PATH).verify_chain()
