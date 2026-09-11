from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def headers(role: str = "WELFARE_OFFICER", purpose: str = "WELFARE_SUPPORT") -> dict[str, str]:
    return {"X-Fortify-Role": role, "X-Fortify-Purpose": purpose}


def test_dashboard_overview_is_read_only_and_privacy_preserving() -> None:
    with TestClient(app) as client:
        response = client.get("/api/dashboard/overview", headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert body["personnel_count"] == 500
    assert body["as_of_date"] == "2026-06-29"
    text = str(body).lower()
    assert "mood_score" not in text
    assert "energy_score" not in text
    assert "sleep_quality" not in text
    assert "perceived_stress" not in text
    assert "support_request" not in text


def test_dashboard_individual_detail_requires_welfare_purpose() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/dashboard/person/P-0001",
            headers=headers("COMMANDER", "AGGREGATE_OPERATIONS"),
        )
    assert response.status_code == 403


def test_dashboard_forbids_missing_security_context() -> None:
    with TestClient(app) as client:
        response = client.get("/api/dashboard/overview")
    assert response.status_code == 401


def test_dashboard_trend_and_units_are_available_to_authorized_welfare_view() -> None:
    with TestClient(app) as client:
        trend = client.get("/api/dashboard/trend?days=14", headers=headers())
        units = client.get("/api/dashboard/units", headers=headers())
    assert trend.status_code == 200
    assert trend.json()["days"] == 14
    assert units.status_code == 200
    assert len(units.json()["units"]) == 18


def test_dashboard_api_does_not_expose_raw_wellness_columns() -> None:
    with TestClient(app) as client:
        detail = client.get("/api/dashboard/person/P-0001", headers=headers())
    assert detail.status_code == 200
    text = detail.text.lower()
    for forbidden in ("mood_score", "energy_score", "sleep_quality", "perceived_stress", "support_request"):
        assert forbidden not in text
