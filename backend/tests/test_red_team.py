"""FORTIFY red-team suite.

Each test is one attack from the red-team campaign, with the expected outcome
stated in the docstring and the actual outcome asserted. Every test here is
marked ``red_team`` so the CI run can publish a machine-readable expected/
actual/verdict report (see conftest hook) — a passing suite IS the evidence
that these attacks fail.

Where an attack is already covered by a functional test elsewhere, this file
keeps its own copy deliberately: the red-team suite must stand alone.
"""
from __future__ import annotations

import json
import socket
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security.rbac import UnitScope as _UnitScope
_SCRIPT_SCOPE = _UnitScope.script()

# Every test in this module is part of the red-team campaign; the conftest
# hook records expected/actual/verdict for the evidence report.
pytestmark = pytest.mark.red_team


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


WELFARE = {"X-Fortify-Role": "WELFARE_OFFICER", "X-Fortify-Purpose": "WELFARE_SUPPORT"}
AGGREGATE = {"X-Fortify-Role": "COMMANDER", "X-Fortify-Purpose": "AGGREGATE_OPERATIONS"}
AUDIT = {"X-Fortify-Role": "AUDITOR", "X-Fortify-Purpose": "AUDIT"}
INFRA = {"X-Fortify-Role": "SYSTEM_ADMINISTRATOR", "X-Fortify-Purpose": "INFRASTRUCTURE_ADMIN"}


def test_missing_authentication_is_rejected(client):
    """EXPECTED: 401 with no credentials on any protected route."""
    for path in ("/api/dashboard/overview", "/api/dashboard/person/P-0001",
                 "/api/workflow/pending", "/api/dashboard/audit"):
        r = client.get(path)
        assert r.status_code == 401, f"{path}: {r.status_code}"


def test_forged_role_header_is_rejected(client):
    """EXPECTED: 401; unknown roles must not coerce or echo."""
    r = client.get("/api/dashboard/overview", headers={"X-Fortify-Role": "SUPERADMIN", "X-Fortify-Purpose": "AUDIT"})
    assert r.status_code == 401
    assert "SUPERADMIN" not in r.text


def test_forged_purpose_header_is_rejected(client):
    """EXPECTED: 401 or 403; a valid role with an impossible purpose gains nothing."""
    for role, purpose in (("WELFARE_OFFICER", "INFRASTRUCTURE_ADMIN"),
                          ("COMMANDER", "WELFARE_SUPPORT"),
                          ("AUDITOR", "WELFARE_SUPPORT"),
                          ("SYSTEM_ADMINISTRATOR", "AUDIT")):
        r = client.get("/api/dashboard/person/P-0001",
                       headers={"X-Fortify-Role": role, "X-Fortify-Purpose": purpose})
        assert r.status_code in (401, 403), f"{role}/{purpose}: {r.status_code}"


def test_privilege_escalation_paths_are_closed(client):
    """EXPECTED: each role confined to its matrix; no cross-purpose access."""
    attempts = [
        (WELFARE, "/api/dashboard/system-health", 403),
        (WELFARE, "/api/dashboard/audit", 403),
        (AGGREGATE, "/api/dashboard/person/P-0001", 403),
        (AGGREGATE, "/api/workflow/pending", 403),
        (AUDIT, "/api/dashboard/personnel", 403),
        (AUDIT, "/api/dashboard/units", 403),
        (INFRA, "/api/dashboard/person/P-0001", 403),
        (INFRA, "/api/workflow/pending", 403),
    ]
    for headers, path, expected in attempts:
        r = client.get(path, headers=headers)
        assert r.status_code == expected, f"{headers['X-Fortify-Role']} -> {path}: {r.status_code}"


def test_object_id_enumeration_has_no_oracle(client):
    """EXPECTED: forbidden callers cannot distinguish existing from absent ids."""
    real = client.get("/api/dashboard/person/P-0001", headers=AGGREGATE)
    fake = client.get("/api/dashboard/person/P-9999", headers=AGGREGATE)
    assert real.status_code == fake.status_code == 403
    real_w = client.get("/api/workflow/WF-0000000000000000", headers=AGGREGATE)
    fake_w = client.get("/api/workflow/WF-ffffffffffffffff", headers=AGGREGATE)
    assert real_w.status_code == fake_w.status_code == 403


def test_path_traversal_in_identifiers_is_inert(client):
    """EXPECTED: traversal payloads are just unknown ids — 404, no files touched."""
    for payload in ("../../etc/passwd", "..%2F..%2Fetc%2Fpasswd", "P-0001/../../secret",
                    "C:\\Windows\\system32", "....//....//data"):
        r = client.get(f"/api/dashboard/person/{payload}", headers=WELFARE)
        assert r.status_code == 404, f"{payload}: {r.status_code}"
        assert "passwd" not in r.text and "Windows" not in r.text


def test_sql_injection_in_paths_and_params_is_inert(client):
    """EXPECTED: bound parameters; payloads behave as unknown identifiers."""
    payloads = ["WF-' OR '1'='1", "P-0001'; DROP TABLE workflow_items;--", "P-0001 UNION SELECT 1"]
    for payload in payloads:
        r = client.get(f"/api/workflow/{payload}", headers=WELFARE)
        assert r.status_code == 404, f"{payload}: {r.status_code}"
    r = client.get("/api/dashboard/personnel?query=P-0001'%20OR%20'1'='1", headers=WELFARE)
    assert r.status_code in (200, 404)  # filter is pandas-based; payload is inert text


def test_malformed_json_yields_consistent_envelope(client):
    """EXPECTED: 422 with {detail: string}; no parser internals leaked."""
    r = client.post("/api/workflow/WF-x/transition", headers=WELFARE, content=b"{this is not json")
    assert r.status_code == 422
    body = r.json()
    assert isinstance(body["detail"], str)
    assert "Expecting" not in body["detail"]


def test_oversized_request_payload_is_rejected(client):
    """EXPECTED: oversized free-text rejected by schema before any processing."""
    r = client.post("/api/workflow/WF-x/feedback", headers=WELFARE,
                    json={"helpfulness": 3, "comment": "x" * 100_000})
    assert r.status_code in (400, 404, 422)


def test_header_injection_cannot_smuggle_a_role(client):
    """EXPECTED: a CRLF-bearing credential value is not a valid role - the
    request is refused, and the injected text never becomes application state.
    (HTTP-level header-splitting protection is the server's (h11/uvicorn)
    responsibility; the ASGI transport used here bypasses that layer, so this
    test proves the application-side outcome: unknown value -> 401.)"""
    r = client.get("/api/dashboard/overview",
                   headers={"X-Fortify-Role": "WELFARE_OFFICER\r\nX-Injected: yes",
                            "X-Fortify-Purpose": "WELFARE_SUPPORT"})
    assert r.status_code == 401
    assert "X-Injected" not in r.text


def test_audit_truncation_is_detected(tmp_path):
    """EXPECTED: verify() fails on a rolled-back log."""
    from app.security.audit import AuditEvent, AuditLog
    now = datetime.now(timezone.utc).isoformat()
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    for i in range(4):
        log.append(AuditEvent("T", "R", "P", "ALLOWED", "r", now, {}))
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
    assert AuditLog(path).verify().valid is False


def test_audit_full_history_rewrite_is_detected(tmp_path):
    """EXPECTED: recomputing the whole chain after altering events fails against
    the signed anchor."""
    import hashlib
    from app.security.audit import AuditEvent, AuditLog
    now = datetime.now(timezone.utc).isoformat()
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    for i in range(4):
        log.append(AuditEvent("WORKFLOW_TRANSITION", "WELFARE_OFFICER", "WELFARE_SUPPORT",
                              "DENIED", f"/api/workflow/WF-{i}", now, {}))
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    previous = "GENESIS"
    for record in records:
        record["outcome"] = "ALLOWED"
        record.pop("event_hash")
        record["previous_hash"] = previous
        previous = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        record["event_hash"] = previous
    path.write_text("\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in records) + "\n",
                    encoding="utf-8")
    assert AuditLog(path).verify().valid is False


def test_audit_anchor_deletion_fails_closed(tmp_path):
    """EXPECTED: no anchor -> the log cannot be shown complete -> invalid."""
    from app.security.audit import AuditEvent, AuditLog
    now = datetime.now(timezone.utc).isoformat()
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append(AuditEvent("T", "R", "P", "ALLOWED", "r", now, {}))
    Path(f"{path}.anchor").unlink()
    verification = AuditLog(path).verify()
    assert verification.valid is False and verification.anchored is False


def test_log_injection_cannot_smuggle_lines(client):
    """EXPECTED: identifiers with newlines are redacted/neutralised in logs."""
    import logging
    from app.observability import redact
    payload = redact("P-0001\nINJECTED LOG LINE Fake level=ERROR")
    assert "\n" not in str(payload) or "[redacted]" in str(payload)


def test_error_responses_do_not_leak_internals(client):
    """EXPECTED: a forced internal error returns a generic message + request id."""
    from app.api.routes import dashboard as dashboard_module
    original = dashboard_module._dashboard_frame
    def boom():
        raise RuntimeError("secret/data/personnel.csv mood_score=4.5 leaked")
    dashboard_module._dashboard_frame = boom
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/api/dashboard/overview", headers=WELFARE)
    finally:
        dashboard_module._dashboard_frame = original
    assert r.status_code == 500
    assert "personnel.csv" not in r.text and "mood_score" not in r.text
    assert r.json().get("request_id")


def test_metrics_and_health_expose_no_person_data(client):
    """EXPECTED: operational surfaces carry no person identifiers or welfare fields."""
    with TestClient(app) as c:
        metrics = c.get("/metrics").text
        health = c.get("/health").text
        ready = c.get("/ready").text
    for surface in (metrics, health, ready):
        assert "P-00" not in surface
        for field in ("mood_score", "perceived_stress", "sleep_quality"):
            assert field not in surface


def test_secret_exposure_via_env_reflection_is_prevented(client):
    """EXPECTED: no endpoint reflects environment or configuration values."""
    with TestClient(app) as c:
        for path in ("/health", "/ready", "/version", "/metrics"):
            body = c.get(path).text.lower()
            for secret_name in ("fortify_oidc", "hmac", "password", "secret="):
                assert secret_name not in body, f"{path} reflected {secret_name}"


def test_unauthorized_ingestion_is_blocked_by_default(client):
    """EXPECTED: ingestion is opt-in and infrastructure-gated; off by default."""
    r = client.post("/api/ingest/duty_events", headers=INFRA, json={"rows": []})
    assert r.status_code in (404, 403, 501), f"ingestion answered {r.status_code} while disabled"


# ---------------------------------------------------------------------------
# Workflow red team (section: concurrent officers, stale updates, edge states)
# ---------------------------------------------------------------------------

def test_two_officers_same_case_one_wins_other_gets_conflict(client):
    """EXPECTED: two officers performing the SAME transition on the same case:
    exactly one 200, one 400 - regardless of the case's current state."""
    from app.services import workflow as wf
    items = wf.list_items(pending_only=True, limit=50, unit_scope=_SCRIPT_SCOPE)
    if not items:
        pytest.skip("no pending items")
    item = items[0]
    item_id = item["workflow_item_id"]
    current = item["workflow_state"]
    valid_targets = {"NEW": "ACKNOWLEDGED", "ACKNOWLEDGED": "IN_REVIEW",
                     "IN_REVIEW": "DEFERRED", "DEFERRED": "IN_REVIEW",
                     "SUPPORT_PLANNED": "DEFERRED"}
    target = valid_targets.get(current)
    if target is None:
        pytest.skip(f"no deterministic valid transition from {current}")
    with TestClient(app) as c:
        first = c.post(f"/api/workflow/{item_id}/transition", headers=WELFARE,
                       json={"new_state": target, "reason_code": "OFFICER-A"})
        second = c.post(f"/api/workflow/{item_id}/transition", headers=WELFARE,
                        json={"new_state": target, "reason_code": "OFFICER-B"})
    codes = sorted([first.status_code, second.status_code])
    assert codes[0] == 200 and codes[1] == 400, f"{current}->{target}: {codes}"


def test_stale_update_gets_conflict_not_silent_overwrite(client):
    """EXPECTED: expected_state mismatch -> 400 naming the conflict."""
    from app.services import workflow as wf
    items = wf.list_items(pending_only=True, limit=1, unit_scope=_SCRIPT_SCOPE)
    if not items:
        pytest.skip("no pending items")
    item_id = items[0]["workflow_item_id"]
    with TestClient(app) as c:
        r = c.post(f"/api/workflow/{item_id}/transition", headers=WELFARE,
                   json={"new_state": "ACKNOWLEDGED", "reason_code": "STALE",
                         "expected_state": "SUPPORT_COMPLETED"})
    assert r.status_code == 400
    assert "changed" in r.json()["detail"].lower()


def test_reopen_after_closure_is_rejected(client):
    """EXPECTED: terminal states accept no transitions."""
    with TestClient(app) as c:
        closed = _advance_to(c, "CLOSED")
        assert closed, "could not reach a terminal state through the real endpoints"
        r = c.post(f"/api/workflow/{closed}/transition", headers=WELFARE,
                   json={"new_state": "IN_REVIEW", "reason_code": "REOPEN-ATTACK"})
        assert r.status_code == 400, f"terminal case accepted {r.status_code}"


def test_feedback_without_support_record_is_rejected(client):
    """EXPECTED: 400 — feedback requires a completed support event."""
    from app.services import workflow as wf
    items = wf.list_items(pending_only=True, limit=50, unit_scope=_SCRIPT_SCOPE)
    fresh = next((i for i in items if not i.get("support_completed_at")), None)
    assert fresh, "no case without a support event; the demo store is not pristine"
    with TestClient(app) as c:
        r = c.post(f"/api/workflow/{fresh['workflow_item_id']}/feedback", headers=WELFARE,
                   json={"helpfulness": 4})
    assert r.status_code == 400


def test_duplicate_followup_completion_is_idempotent(client):
    """EXPECTED: completing an already-completed follow-up replays 200."""
    with TestClient(app) as c:
        followups = c.get("/api/workflow/follow-ups", headers=WELFARE).json()["items"]
        done = next((f for f in followups if f["status"] == "COMPLETED"), None)
        if done is None:
            item_id = _advance_to(c, "SUPPORT_COMPLETED")
            assert item_id, "could not reach SUPPORT_COMPLETED to schedule a follow-up"
            scheduled = c.post(f"/api/workflow/{item_id}/follow-up", headers=WELFARE,
                               json={"scheduled_for": "2026-07-01T09:00:00+00:00"})
            assert scheduled.status_code == 200, scheduled.text
            followups = c.get("/api/workflow/follow-ups", headers=WELFARE).json()["items"]
            open_fu = next((f for f in followups if f["workflow_item_id"] == item_id), None)
            assert open_fu, "scheduled follow-up did not appear in the follow-up queue"
            first = c.post(f"/api/workflow/follow-ups/{open_fu['followup_id']}/complete", headers=WELFARE)
            assert first.status_code == 200, first.text
            done = next((f for f in c.get("/api/workflow/follow-ups", headers=WELFARE)
                         .json()["items"] if f["followup_id"] == open_fu["followup_id"]), None)
        r = c.post(f"/api/workflow/follow-ups/{done['followup_id']}/complete", headers=WELFARE)
    assert r.status_code == 200


PATH_TO = {
    "ACKNOWLEDGED": ["ACKNOWLEDGED"],
    "SUPPORT_COMPLETED": ["ACKNOWLEDGED", "IN_REVIEW", "SUPPORT_PLANNED", "SUPPORT_COMPLETED"],
    "CLOSED": ["ACKNOWLEDGED", "IN_REVIEW", "SUPPORT_PLANNED", "SUPPORT_COMPLETED", "CLOSED"],
}


def _advance_to(c, target: str) -> str | None:
    """Drive a fresh case to ``target`` through the real endpoints.

    Red-team attacks used to SKIP when the demo store happened not to contain the
    state they needed, which meant an attack was silently not attempted. Building
    the precondition through the API makes every attack execute on every run, and
    proves the state machine is what stops the attack rather than an empty table.
    """
    items = c.get("/api/workflow/pending?limit=200", headers=WELFARE).json()["items"]
    path = PATH_TO[target]
    for item in items:
        if item["workflow_state"] != "NEW":
            continue
        item_id = item["workflow_item_id"]
        state = "NEW"
        for step in path:
            moved = c.post(f"/api/workflow/{item_id}/transition", headers=WELFARE,
                           json={"new_state": step, "reason_code": f"RT-PRECONDITION-{step}",
                                 "expected_state": state})
            if moved.status_code != 200:
                break
            state = step
        else:
            return item_id
    return None


def _support_completed_case(c) -> str | None:
    ready = next((i for i in c.get("/api/workflow/pending?limit=200", headers=WELFARE)
                  .json()["items"] if i["workflow_state"] == "SUPPORT_COMPLETED"), None)
    return ready["workflow_item_id"] if ready else _advance_to(c, "SUPPORT_COMPLETED")


def test_followup_requires_timezone_aware_datetime(client):
    """EXPECTED: naive datetime rejected (cannot be compared across systems)."""
    from app.services import workflow as wf
    items = wf.list_items(pending_only=True, limit=100, unit_scope=_SCRIPT_SCOPE)
    supported = next((i for i in items if i["workflow_state"] == "SUPPORT_COMPLETED"), None)
    item_id = supported["workflow_item_id"] if supported else None
    with TestClient(app) as c:
        if item_id is None:
            item_id = _support_completed_case(c)
        assert item_id, "could not reach SUPPORT_COMPLETED through the real endpoints"
        r = c.post(f"/api/workflow/{item_id}/follow-up", headers=WELFARE,
                   json={"scheduled_for": "2026-07-01T09:00:00"})
        assert r.status_code == 400
        # The companion positive case: the same endpoint must accept the aware
        # form, otherwise a blanket 400 would look like a pass.
        ok = c.post(f"/api/workflow/{item_id}/follow-up", headers=WELFARE,
                    json={"scheduled_for": "2026-07-01T09:00:00+00:00"})
        assert ok.status_code == 200
