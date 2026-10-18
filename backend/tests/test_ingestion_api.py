"""Ingestion API tests: opt-in, infrastructure-gated, validation-only."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


INFRA = {"X-Fortify-Role": "SYSTEM_ADMINISTRATOR", "X-Fortify-Purpose": "INFRASTRUCTURE_ADMIN"}
WELFARE = {"X-Fortify-Role": "WELFARE_OFFICER", "X-Fortify-Purpose": "WELFARE_SUPPORT"}

CSV = (
    "duty_event_id,person_id,date,duration_hours,duty_type,night_shift,intensity_level\n"
    "D-1,P-0001,2026-06-28,8.0,DAY,0,3\n"
    "D-2,P-0002,2026-06-28,9.5,NIGHT,1,4\n"
)


def test_ingestion_is_invisible_when_disabled(client):
    """EXPECTED: 404 - the surface does not exist by default."""
    r = client.post("/api/ingest/duty_events", headers=INFRA,
                    files={"file": ("batch.csv", CSV.encode())},
                    data={"source_system": "hr", "batch_id": "b1"})
    assert r.status_code == 404


def test_ingestion_requires_infrastructure_purpose(client, monkeypatch):
    """EXPECTED: welfare purpose cannot ingest even when enabled."""
    monkeypatch.setenv("FORTIFY_ENABLE_INGEST", "1")
    with TestClient(app) as c:
        r = c.post("/api/ingest/duty_events", headers=WELFARE,
                   files={"file": ("batch.csv", CSV.encode())},
                   data={"source_system": "hr", "batch_id": "b1"})
    assert r.status_code == 403


def test_valid_batch_is_accepted_and_staged(client, monkeypatch, tmp_path):
    """EXPECTED: accepted batch staged; response carries provenance."""
    import app.api.routes.ingestion as ing
    monkeypatch.setenv("FORTIFY_ENABLE_INGEST", "1")
    monkeypatch.setattr(ing, "STAGING_DIR", tmp_path / "staging")
    with TestClient(app) as c:
        r = c.post("/api/ingest/duty_events", headers=INFRA,
                   files={"file": ("batch.csv", CSV.encode())},
                   data={"source_system": "hr-roster", "batch_id": "b-2026-10-02",
                         "schema_version": "1"})
    body = r.json()
    assert body["accepted"] is True
    assert body["provenance"]["source_system"] == "hr-roster"
    assert body["provenance"]["validation_status"] == "ACCEPTED"
    assert (tmp_path / "staging" / "duty_events" / "staged-b-2026-10-02.csv").exists()


def test_invalid_batch_is_rejected_in_full(client, monkeypatch, tmp_path):
    """EXPECTED: impossible values reject the WHOLE batch; nothing staged."""
    import app.api.routes.ingestion as ing
    monkeypatch.setenv("FORTIFY_ENABLE_INGEST", "1")
    monkeypatch.setattr(ing, "STAGING_DIR", tmp_path / "staging")
    bad = CSV.replace("8.0", "40.0")
    with TestClient(app) as c:
        r = c.post("/api/ingest/duty_events", headers=INFRA,
                   files={"file": ("batch.csv", bad.encode())},
                   data={"source_system": "hr-roster", "batch_id": "b-bad"})
    body = r.json()
    assert body["accepted"] is False
    assert any(rj["check"] == "impossible_values" for rj in body["rejections"])
    assert not (tmp_path / "staging" / "duty_events" / "staged-b-bad.csv").exists()


def test_schema_version_mismatch_rejects(client, monkeypatch, tmp_path):
    """EXPECTED: a batch declaring a different schema version is refused."""
    import app.api.routes.ingestion as ing
    monkeypatch.setenv("FORTIFY_ENABLE_INGEST", "1")
    monkeypatch.setattr(ing, "STAGING_DIR", tmp_path / "staging")
    with TestClient(app) as c:
        r = c.post("/api/ingest/duty_events", headers=INFRA,
                   files={"file": ("batch.csv", CSV.encode())},
                   data={"source_system": "hr", "batch_id": "b2", "schema_version": "2"})
    body = r.json()
    assert body["accepted"] is False
    assert any(rj["check"] == "schema_version_mismatch" for rj in body["rejections"])


def test_ingestion_authorization_is_audited(monkeypatch, tmp_path):
    """Every authorization decision must leave a tamper-evident record.

    The ingestion routes originally called the shared guard without an audit
    path, so an operator's access to the external-data door - and any refusal
    of it - was enforced but never written to the chain the auditor reads.
    """
    import json
    import app.api.routes.ingestion as ing
    audit_file = tmp_path / "audit.jsonl"
    monkeypatch.setenv("FORTIFY_ENABLE_INGEST", "1")
    monkeypatch.setattr(ing, "STAGING_DIR", tmp_path / "staging")
    monkeypatch.setattr(ing, "AUDIT_PATH", audit_file)

    with TestClient(app) as c:
        assert c.get("/api/ingest/status", headers=INFRA).status_code == 200
        assert c.post("/api/ingest/duty_events", headers=WELFARE,
                      files={"file": ("batch.csv", CSV.encode())},
                      data={"source_system": "hr", "batch_id": "b-audit"}).status_code == 403

    records = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").splitlines()]
    decisions = [r for r in records if r.get("event_type") == "ACCESS_CONTROL"]
    outcomes = {(d.get("details") or {}).get("view"): d.get("outcome") for d in decisions}
    assert "infrastructure" in outcomes, f"no infrastructure ACCESS_CONTROL record in {decisions}"
    assert "DENIED" in outcomes.values(), "a refused ingestion attempt was not audited"
    assert any(d.get("resource", "").startswith("/api/ingest/") for d in decisions)


def test_ingestion_status_reports_quality(client, monkeypatch, tmp_path):
    """EXPECTED: quality report aggregates accepted/rejected/invalid counts."""
    import app.api.routes.ingestion as ing
    monkeypatch.setenv("FORTIFY_ENABLE_INGEST", "1")
    monkeypatch.setattr(ing, "STAGING_DIR", tmp_path / "staging")
    with TestClient(app) as c:
        status = c.get("/api/ingest/status", headers=INFRA)
    assert status.status_code == 200
    body = status.json()
    assert body["enabled"] is True
    assert "duty_events" in body["datasets"]
    assert "last_ingestion" in body["datasets"]["duty_events"]
