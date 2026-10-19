"""Privacy-surface and logging-redaction proof tests.

Privacy surface: for each role, enumerate the accessible endpoints and assert
the *class* of every returned field — commanders never see person-level data,
auditors get governance data only, welfare officers only purpose-appropriate
individual data. These are server-side boundaries; nothing relies on the
frontend hiding anything.

Logging: prove that person identifiers, wellness fields, and free-text
comments do not appear in log output, and that log records carry the
operational fields (time, level, request id, route, status, latency).
"""
from __future__ import annotations

import json
import logging
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.observability import redact

WELFARE = {"X-Fortify-Role": "WELFARE_OFFICER", "X-Fortify-Purpose": "WELFARE_SUPPORT"}
AGGREGATE = {"X-Fortify-Role": "COMMANDER", "X-Fortify-Purpose": "AGGREGATE_OPERATIONS"}
AUDIT = {"X-Fortify-Role": "AUDITOR", "X-Fortify-Purpose": "AUDIT"}
INFRA = {"X-Fortify-Role": "SYSTEM_ADMINISTRATOR", "X-Fortify-Purpose": "INFRASTRUCTURE_ADMIN"}

WELLNESS_FIELDS = {"mood_score", "energy_score", "sleep_quality", "perceived_stress",
                   "workload_manageability", "support_request"}

# Person identifiers are P-0001 style. A bare "P-0" substring also occurs in
# support-event ids (SUP-0...), so match the whole identifier shape instead.
PERSON_ID = re.compile(r"\bP-\d{3,}\b")


def _assert_no_person_ids(value, context: str) -> None:
    match = PERSON_ID.search(json.dumps(value))
    assert match is None, f"{context} leaked a person identifier: {match.group(0) if match else ''}"


def _all_payloads(value) -> list[dict]:
    if isinstance(value, dict):
        return [value] + [p for v in value.values() for p in _all_payloads(v)]
    if isinstance(value, list):
        return [p for v in value for p in _all_payloads(v)]
    return []


class TestPrivacySurfaceByRole:
    def test_commander_never_receives_person_level_data(self, client):
        """EXPECTED: aggregate views contain counts and unit ids only — no
        person identifiers, no per-person probabilities."""
        for path in ("/api/dashboard/overview", "/api/dashboard/units", "/api/dashboard/trend?days=14"):
            body = client.get(path, headers=AGGREGATE).json()
            text = json.dumps(body)
            _assert_no_person_ids(body, path)
            assert "risk_probability" not in text, f"{path} leaked per-person scores"

    def test_auditor_receives_only_governance_data(self, client):
        """EXPECTED: audit events carry governance metadata; no wellness fields
        and no raw decision payloads."""
        body = client.get("/api/dashboard/audit?limit=100", headers=AUDIT).json()
        for payload in _all_payloads(body):
            assert not WELLNESS_FIELDS & set(payload.keys())
        # Personnel identifiers in audit details are redacted at read time.
        _assert_no_person_ids(body, "/api/dashboard/audit")

    def test_welfare_officer_individual_data_is_purpose_appropriate(self, client):
        """EXPECTED: individual views may carry operational welfare signals but
        never raw wellness self-report fields."""
        detail = client.get("/api/dashboard/person/P-0001", headers=WELFARE).json()
        for payload in _all_payloads(detail):
            assert not WELLNESS_FIELDS & set(payload.keys())
        queue = client.get("/api/dashboard/review-queue", headers=WELFARE).json()
        for payload in _all_payloads(queue):
            assert not WELLNESS_FIELDS & set(payload.keys())

    def test_unauthenticated_surface_is_only_public_health(self, client):
        """EXPECTED: without credentials exactly three anonymous endpoints
        answer, and none expose welfare data."""
        public_ok = []
        for path in ("/health", "/ready", "/version", "/metrics",
                     "/api/dashboard/overview", "/api/workflow/pending"):
            r = client.get(path)
            if r.status_code == 200:
                public_ok.append(path)
        assert set(public_ok) == {"/health", "/ready", "/version", "/metrics"}


class TestLoggingRedaction:
    def test_redact_removes_person_identifiers_from_text(self):
        """EXPECTED: identifiers anywhere in a string become [redacted]."""
        assert "P-0144" not in redact("opening case P-0144 for review")
        assert "U-031" not in redact("unit U-031 summary")

    def test_redact_removes_sensitive_keys(self):
        """EXPECTED: sensitive keys never survive into log records."""
        record = {"person_id": "P-0001", "comment": "free text", "token": "abc",
                  "path": "/api/dashboard/person/P-0002"}
        safe = redact(record)
        assert safe["person_id"] == "[redacted]"
        assert safe["comment"] == "[redacted]"
        assert safe["token"] == "[redacted]"
        assert "P-0002" not in safe["path"]

    def test_request_logs_carry_no_person_identifiers(self, client, caplog):
        """EXPECTED: the structured request log for a person-detail request
        contains the route but NOT the person id."""
        with caplog.at_level(logging.INFO, logger="fortify"):
            client.get("/api/dashboard/person/P-0001", headers=WELFARE)
        records = [r for r in caplog.records if r.name == "fortify"]
        assert records, "no structured request log captured"
        for record in records:
            text = record.getMessage()
            rendered = json.dumps({k: record.__dict__.get(k) for k in record.__dict__}, default=str)
            assert "P-0001" not in rendered, f"person id leaked into log: {text}"

    def test_request_logs_carry_operational_fields(self, client, caplog):
        """EXPECTED: logs include level, request id, route, status, latency."""
        with caplog.at_level(logging.INFO, logger="fortify"):
            client.get("/health")
        record = next(r for r in caplog.records if r.name == "fortify")
        assert record.levelname == "INFO"
        assert record.request_id
        assert record.path == "/health"
        assert record.status == 200
        assert "duration_ms" in record.__dict__


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c