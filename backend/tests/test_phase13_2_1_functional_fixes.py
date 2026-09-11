from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

WELFARE = {"X-Fortify-Role": "WELFARE_OFFICER", "X-Fortify-Purpose": "WELFARE_SUPPORT"}
COMMAND = {"X-Fortify-Role": "COMMANDER", "X-Fortify-Purpose": "AGGREGATE_OPERATIONS"}


def test_welfare_workspace_can_access_aggregate_unit_view_without_changing_policy() -> None:
    with TestClient(app) as client:
        response = client.get("/api/dashboard/units", headers={**WELFARE, "X-Fortify-Purpose": "AGGREGATE_OPERATIONS"})
        denied = client.get("/api/dashboard/audit", headers=WELFARE)
    assert response.status_code == 200
    assert len(response.json()["units"]) == 18
    assert denied.status_code == 403


def test_global_search_returns_real_person_and_unit_records() -> None:
    with TestClient(app) as client:
        person = client.get("/api/dashboard/search?query=P-0144", headers=WELFARE)
        unit = client.get("/api/dashboard/search?query=U-031", headers=WELFARE)
    assert person.status_code == 200 and person.json()["results"][0]["key"] == "P-0144"
    assert unit.status_code == 200 and unit.json()["results"][0]["key"] == "U-031"


def test_real_person_profiles_remain_dynamic() -> None:
    with TestClient(app) as client:
        a = client.get("/api/dashboard/person/P-0144", headers=WELFARE)
        b = client.get("/api/dashboard/person/P-0402", headers=WELFARE)
    assert a.status_code == 200 and b.status_code == 200
    da, db = a.json(), b.json()
    assert da["person_id"] != db["person_id"]
    assert (da["unit_id"], da["role"], da["latest"]["recommended_action"], da["latest"]["feasibility_status"]) != (db["unit_id"], db["role"], db["latest"]["recommended_action"], db["latest"]["feasibility_status"])


def test_pending_workflow_rows_carry_real_unit_ids() -> None:
    with TestClient(app) as client:
        response = client.get("/api/workflow/pending?limit=200", headers=WELFARE)
    assert response.status_code == 200
    items = response.json()["items"]
    assert items
    assert all(item.get("unit_id") for item in items)


def test_auth_errors_are_not_exposed_as_raw_json_through_frontend_api_policy() -> None:
    # The frontend API client maps 401/403 to a product-level access message;
    # backend policy must continue to return the actual 403 for unauthorized governance access.
    with TestClient(app) as client:
        response = client.get("/api/dashboard/audit", headers=WELFARE)
    assert response.status_code == 403
    assert response.json()["detail"] == "Audit view requires auditor authorization."
