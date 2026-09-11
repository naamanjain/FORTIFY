from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.api.routes import dashboard as dashboard_route


WELFARE = {"X-Fortify-Role": "WELFARE_OFFICER", "X-Fortify-Purpose": "WELFARE_SUPPORT"}
COMMAND = {"X-Fortify-Role": "COMMANDER", "X-Fortify-Purpose": "AGGREGATE_OPERATIONS"}
AUDITOR = {"X-Fortify-Role": "AUDITOR", "X-Fortify-Purpose": "AUDIT"}
ADMIN = {"X-Fortify-Role": "SYSTEM_ADMINISTRATOR", "X-Fortify-Purpose": "INFRASTRUCTURE_ADMIN"}


def test_personnel_directory_is_role_bound_and_privacy_preserving(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dashboard_route, "AUDIT_PATH", tmp_path / "audit.jsonl")
    with TestClient(app) as client:
        response = client.get("/api/dashboard/personnel", headers=WELFARE)
        denied = client.get("/api/dashboard/personnel", headers=COMMAND)
    assert response.status_code == 200
    body = response.json()
    assert body["total_personnel"] == 500
    assert body["items"]
    assert "perceived_stress" not in response.text.lower()
    assert denied.status_code == 403


def test_search_is_aggregate_first_for_commanders(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dashboard_route, "AUDIT_PATH", tmp_path / "audit.jsonl")
    with TestClient(app) as client:
        person = client.get("/api/dashboard/search?query=P-0001", headers=WELFARE)
        command = client.get("/api/dashboard/search?query=U-011", headers=COMMAND)
    assert person.status_code == 200
    assert any(r["type"] == "PERSONNEL" and r["key"] == "P-0001" for r in person.json()["results"])
    assert command.status_code == 200
    assert all(r["type"] == "UNIT" for r in command.json()["results"])


def test_unit_detail_is_aggregate_only(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dashboard_route, "AUDIT_PATH", tmp_path / "audit.jsonl")
    with TestClient(app) as client:
        allowed = client.get("/api/dashboard/unit/U-011", headers=COMMAND)
        denied = client.get("/api/dashboard/unit/U-011", headers=WELFARE)
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["personnel"] > 0
    assert "P-0001" not in allowed.text
    assert denied.status_code == 403


def test_data_sources_and_system_health_expose_metadata_not_raw_wellness(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dashboard_route, "AUDIT_PATH", tmp_path / "audit.jsonl")
    with TestClient(app) as client:
        sources = client.get("/api/dashboard/data-sources", headers=COMMAND)
        health = client.get("/api/dashboard/system-health", headers=ADMIN)
    assert sources.status_code == 200
    assert health.status_code == 200
    assert "mood_score" not in sources.text.lower()
    assert "perceived_stress" not in sources.text.lower()
    assert health.json()["synthetic_demo"] is True
    assert health.json()["governance"]["audit_chain"] == "Healthy"


def test_audit_view_requires_auditor_role(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dashboard_route, "AUDIT_PATH", tmp_path / "audit.jsonl")
    with TestClient(app) as client:
        denied = client.get("/api/dashboard/audit", headers=WELFARE)
        allowed = client.get("/api/dashboard/audit", headers=AUDITOR)
    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["chain_valid"] is True
