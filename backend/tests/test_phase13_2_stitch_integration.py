from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

WELFARE = {"X-Fortify-Role": "WELFARE_OFFICER", "X-Fortify-Purpose": "WELFARE_SUPPORT"}
COMMAND = {"X-Fortify-Role": "COMMANDER", "X-Fortify-Purpose": "AGGREGATE_OPERATIONS"}
AUDITOR = {"X-Fortify-Role": "AUDITOR", "X-Fortify-Purpose": "AUDIT"}


def test_person_profiles_are_dynamic_and_return_real_context() -> None:
    with TestClient(app) as client:
        first = client.get("/api/dashboard/person/P-0144", headers=WELFARE)
        second = client.get("/api/dashboard/person/P-0209", headers=WELFARE)
    assert first.status_code == 200 and second.status_code == 200
    a, b = first.json(), second.json()
    assert a["person_id"] == "P-0144" and b["person_id"] == "P-0209"
    assert a["unit_id"] and b["unit_id"]
    assert (a["unit_id"], a["role"]) != (b["unit_id"], b["role"])
    assert "P-0144" not in second.text
    assert "perceived_stress" not in first.text.lower()


def test_unit_command_is_aggregate_only() -> None:
    with TestClient(app) as client:
        allowed = client.get("/api/dashboard/unit/U-031", headers=COMMAND)
        denied = client.get("/api/dashboard/unit/U-031", headers=WELFARE)
    assert allowed.status_code == 200
    assert allowed.json()["unit_id"] == "U-031"
    assert "P-" not in allowed.text
    assert denied.status_code == 403


def test_data_and_governance_surfaces_use_real_protected_metadata() -> None:
    with TestClient(app) as client:
        sources = client.get("/api/dashboard/data-sources", headers=COMMAND)
        audit = client.get("/api/dashboard/audit", headers=AUDITOR)
    assert sources.status_code == 200 and audit.status_code == 200
    assert sources.json()["environment"].lower().startswith("synthetic")
    assert audit.json()["chain_valid"] is True
    assert "mood_score" not in sources.text.lower()
    assert "perceived_stress" not in sources.text.lower()
