from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
import app.services.workflow as workflow

HEADERS = {"X-Fortify-Role": "WELFARE_OFFICER", "X-Fortify-Purpose": "WELFARE_SUPPORT"}
AUDITOR = {"X-Fortify-Role": "AUDITOR", "X-Fortify-Purpose": "AUDIT"}

@pytest.fixture()
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "workflow.db"
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(workflow, "_db_path", lambda: db)
    from app.api.routes import workflow as workflow_route
    monkeypatch.setattr(workflow_route, "AUDIT_PATH", audit)
    return db

def item_id() -> str:
    return workflow._workflow_id("P-0001", "2026-06-29")

def advance_to_support_completed(client: TestClient) -> str:
    wid = item_id()
    for state, reason in [
        ("ACKNOWLEDGED", "ACKNOWLEDGE_REVIEW"),
        ("IN_REVIEW", "START_REVIEW"),
        ("SUPPORT_PLANNED", "PLAN_SUPPORT"),
        ("SUPPORT_COMPLETED", "SUPPORT_COMPLETED_BY_HUMAN"),
    ]:
        response = client.post(f"/api/workflow/{wid}/transition", headers=HEADERS, json={"new_state": state, "reason_code": reason})
        assert response.status_code == 200, response.text
    return wid

def test_support_completion_creates_persistent_support_event(isolated_store: Path) -> None:
    with TestClient(main.app) as client:
        wid = advance_to_support_completed(client)
        payload = client.get(f"/api/workflow/{wid}", headers=HEADERS).json()
    assert payload["workflow_state"] == "SUPPORT_COMPLETED"
    assert payload["support_event"]["support_event_id"].startswith("SUP-")
    assert payload["support_event"]["actor_role"] == "WELFARE_OFFICER"
    assert "T" in payload["support_event"]["completed_at"]


def test_feedback_persists_and_missing_feedback_is_neutral(isolated_store: Path) -> None:
    with TestClient(main.app) as client:
        wid = advance_to_support_completed(client)
        before = client.get(f"/api/workflow/{wid}", headers=HEADERS).json()
        assert before["feedback"] is None
        response = client.post(f"/api/workflow/{wid}/feedback", headers=HEADERS,
                               json={"helpfulness": 4, "comment": "Another check-in would be useful.", "follow_up_requested": True})
        assert response.status_code == 200, response.text
        after = client.get(f"/api/workflow/{wid}", headers=HEADERS).json()
    assert after["feedback"]["helpfulness"] == 4
    assert after["feedback"]["follow_up_requested"] is True
    assert after["feedback"]["comment"] == "Another check-in would be useful."


def test_followup_schedule_reschedule_and_completion_are_persistent(isolated_store: Path) -> None:
    with TestClient(main.app) as client:
        wid = advance_to_support_completed(client)
        scheduled = client.post(f"/api/workflow/{wid}/follow-up", headers=HEADERS,
                                json={"scheduled_for": "2026-09-04T11:10:00+05:30"})
        assert scheduled.status_code == 200, scheduled.text
        first = scheduled.json()["followup"]
        assert first["status"] == "SCHEDULED"
        followups = client.get("/api/workflow/follow-ups", headers=HEADERS).json()
        assert followups["count"] == 1
        assert followups["items"][0]["person_id"] == "P-0001"
        rescheduled = client.post(f"/api/workflow/{wid}/follow-up", headers=HEADERS,
                                  json={"scheduled_for": "2026-09-05T12:00:00+05:30"})
        assert rescheduled.status_code == 200
        assert rescheduled.json()["followup"]["scheduled_for"].startswith("2026-09-05T06:30:00")
        completed = client.post(f"/api/workflow/follow-ups/{first['followup_id']}/complete", headers=HEADERS)
        assert completed.status_code == 200, completed.text
        final = client.get(f"/api/workflow/{wid}", headers=HEADERS).json()
    assert final["workflow_state"] == "FOLLOW_UP_COMPLETED"
    assert final["followup"]["status"] == "COMPLETED"
    assert final["followup"]["completed_by_role"] == "WELFARE_OFFICER"


def test_followup_is_not_visible_to_unauthorized_role(isolated_store: Path) -> None:
    with TestClient(main.app) as client:
        wid = advance_to_support_completed(client)
        assert client.post(f"/api/workflow/{wid}/feedback", headers=AUDITOR,
                           json={"helpfulness": 5, "follow_up_requested": False}).status_code == 403
        assert client.get("/api/workflow/follow-ups", headers=AUDITOR).status_code == 403


def test_support_completion_removes_case_from_pending_queue(isolated_store: Path) -> None:
    with TestClient(main.app) as client:
        wid = advance_to_support_completed(client)
        pending = client.get("/api/workflow/pending?limit=200", headers=HEADERS).json()["items"]
    assert wid not in {x["workflow_item_id"] for x in pending}


def test_post_followup_can_close_or_require_further_support(isolated_store: Path) -> None:
    with TestClient(main.app) as client:
        wid = advance_to_support_completed(client)
        scheduled = client.post(f"/api/workflow/{wid}/follow-up", headers=HEADERS,
                                json={"scheduled_for": "2030-09-04T11:10:00+05:30"})
        assert scheduled.status_code == 200
        followup_id = scheduled.json()["followup"]["followup_id"]
        complete = client.post(f"/api/workflow/follow-ups/{followup_id}/complete", headers=HEADERS)
        assert complete.status_code == 200
        closed = client.post(f"/api/workflow/{wid}/transition", headers=HEADERS,
                              json={"new_state": "CLOSED", "reason_code": "CASE_CLOSED_AFTER_FOLLOW_UP"})
    assert closed.status_code == 200
    assert closed.json()["workflow_state"] == "CLOSED"


def test_support_status_preserves_welfare_concern_and_full_timestamp(isolated_store: Path) -> None:
    with TestClient(main.app) as client:
        wid = advance_to_support_completed(client)
        item = client.get(f"/api/workflow/{wid}", headers=HEADERS).json()
    assert item["workflow_state"] == "SUPPORT_COMPLETED"
    assert item["support_event"] is not None
    assert item["support_event"]["actor_role"] == "WELFARE_OFFICER"
    assert item["support_event"]["completed_at"].endswith("+00:00")
    assert item["workflow_state"] != "CLOSED"


def test_reschedule_and_completion_are_auditable(isolated_store: Path) -> None:
    with TestClient(main.app) as client:
        wid = advance_to_support_completed(client)
        scheduled = client.post(f"/api/workflow/{wid}/follow-up", headers=HEADERS, json={"scheduled_for": "2030-09-04T11:10:00+05:30"})
        assert scheduled.status_code == 200
        followup_id = scheduled.json()["followup"]["followup_id"]
        rescheduled = client.post(f"/api/workflow/{wid}/follow-up", headers=HEADERS, json={"scheduled_for": "2030-09-05T12:00:00+05:30"})
        assert rescheduled.status_code == 200
        completed = client.post(f"/api/workflow/follow-ups/{followup_id}/complete", headers=HEADERS)
        assert completed.status_code == 200
        history = client.get(f"/api/workflow/{wid}/history", headers=HEADERS).json()["events"]
    assert any(e["new_state"] == "FOLLOW_UP_SCHEDULED" for e in history)
    assert any(e["reason_code"] == "FOLLOW_UP_RESCHEDULED" for e in history)
    assert any(e["new_state"] == "FOLLOW_UP_COMPLETED" for e in history)
    assert all("perceived_stress" not in str(e).lower() for e in history)


def test_support_completion_keeps_concern_context_but_changes_support_state(isolated_store: Path) -> None:
    with TestClient(main.app) as client:
        wid = advance_to_support_completed(client)
        item = client.get(f"/api/workflow/{wid}", headers=HEADERS).json()
        feedback = client.post(
            f"/api/workflow/{wid}/feedback", headers=HEADERS,
            json={"helpfulness": 3, "comment": None, "follow_up_requested": False},
        )
    assert feedback.status_code == 200
    assert item["risk_band"] in {"LOW", "MODERATE", "HIGH"}
    assert item["workflow_state"] == "SUPPORT_COMPLETED"
    assert item["risk_band"] != "SUPPORT_COMPLETED"
    assert feedback.json()["feedback"]["comment"] is None
    assert feedback.json()["feedback"]["follow_up_requested"] is False
