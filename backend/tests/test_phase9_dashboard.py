from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.paths import AUDIT_PATH as _DEFAULT_AUDIT_PATH
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


def test_overview_never_returns_personnel_identifiers() -> None:
    """The overview is an aggregate view; it must not be a person export."""
    with TestClient(app) as client:
        for role, purpose in (
            ("WELFARE_OFFICER", "WELFARE_SUPPORT"),
            ("WELFARE_OFFICER", "AGGREGATE_OPERATIONS"),
            ("COMMANDER", "AGGREGATE_OPERATIONS"),
        ):
            body = client.get("/api/dashboard/overview", headers=headers(role, purpose)).json()
            assert "high_priority_cases" not in body
            assert "P-" not in str(body)


def test_overview_is_denied_to_audit_and_infrastructure_purposes() -> None:
    """Neither an auditor nor a sysadmin may read operational welfare data."""
    with TestClient(app) as client:
        for role, purpose in (
            ("AUDITOR", "AUDIT"),
            ("SYSTEM_ADMINISTRATOR", "INFRASTRUCTURE_ADMIN"),
        ):
            assert client.get("/api/dashboard/overview", headers=headers(role, purpose)).status_code == 403


def test_individual_cases_require_welfare_purpose() -> None:
    """The per-person case list is the sensitive view; it must be gated."""
    with TestClient(app) as client:
        allowed = client.get("/api/dashboard/attention", headers=headers("WELFARE_OFFICER", "WELFARE_SUPPORT"))
        for role, purpose in (
            ("AUDITOR", "AUDIT"),
            ("SYSTEM_ADMINISTRATOR", "INFRASTRUCTURE_ADMIN"),
            ("COMMANDER", "AGGREGATE_OPERATIONS"),
            ("WELFARE_OFFICER", "AGGREGATE_OPERATIONS"),
        ):
            denied = client.get("/api/dashboard/attention", headers=headers(role, purpose))
            assert denied.status_code == 403, f"{role}/{purpose} must not reach individual cases"
    assert allowed.status_code == 200
    assert "P-" in str(allowed.json())


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


def test_dashboard_rejects_unrecognized_role() -> None:
    """An unknown role must be rejected, not coerced into a valid one."""
    with TestClient(app) as client:
        response = client.get("/api/dashboard/overview", headers=headers("SUPER_ADMIN", "AUDIT"))
    assert response.status_code == 401
    # The rejection must not echo the attacker's input back.
    assert "SUPER_ADMIN" not in response.text


def test_dashboard_trend_and_units_are_available_to_authorized_welfare_view() -> None:
    """Aggregate views require aggregate purpose, from any permitted role.

    These return no personnel identifiers, so a welfare officer and a commander
    may both read them - but only when the declared purpose matches the view.
    """
    aggregate = headers("WELFARE_OFFICER", "AGGREGATE_OPERATIONS")
    with TestClient(app) as client:
        trend = client.get("/api/dashboard/trend?days=14", headers=aggregate)
        units = client.get("/api/dashboard/units", headers=aggregate)
    assert trend.status_code == 200
    assert trend.json()["days"] == 14
    assert units.status_code == 200
    assert len(units.json()["units"]) == 18


def test_aggregate_views_reject_a_mismatched_purpose() -> None:
    """Declaring welfare purpose does not grant access to an aggregate view."""
    with TestClient(app) as client:
        trend = client.get("/api/dashboard/trend?days=14", headers=headers("WELFARE_OFFICER", "WELFARE_SUPPORT"))
        units = client.get("/api/dashboard/units", headers=headers("WELFARE_OFFICER", "WELFARE_SUPPORT"))
    assert trend.status_code == 403
    assert units.status_code == 403


def test_audit_view_rejects_non_audit_purposes() -> None:
    """An auditor's role alone is not a licence: the purpose must match too."""
    with TestClient(app) as client:
        for role, purpose in (
            ("WELFARE_OFFICER", "WELFARE_SUPPORT"),
            ("COMMANDER", "AGGREGATE_OPERATIONS"),
            ("SYSTEM_ADMINISTRATOR", "INFRASTRUCTURE_ADMIN"),
            ("AUDITOR", "AGGREGATE_OPERATIONS"),
        ):
            response = client.get("/api/dashboard/audit", headers=headers(role, purpose))
            assert response.status_code == 403, f"{role}/{purpose} should be denied"
    with TestClient(app) as client:
        allowed = client.get("/api/dashboard/audit", headers=headers("AUDITOR", "AUDIT"))
    assert allowed.status_code == 200


def test_audit_view_redacts_personnel_identifiers() -> None:
    """The audit screen must not become a de facto personnel export."""
    with TestClient(app) as client:
        body = client.get("/api/dashboard/audit?limit=50", headers=headers("AUDITOR", "AUDIT")).json()
    assert "[redacted:personnel-identifier]" in str(body) or "person_id" not in str(body)


def test_system_health_is_readable_by_auditor_and_infrastructure_admin() -> None:
    """Verifying audit health is part of an auditor's job."""
    with TestClient(app) as client:
        auditor = client.get("/api/dashboard/system-health", headers=headers("AUDITOR", "AUDIT"))
        sysadmin = client.get("/api/dashboard/system-health", headers=headers("SYSTEM_ADMINISTRATOR", "INFRASTRUCTURE_ADMIN"))
        denied = client.get("/api/dashboard/system-health", headers=headers("COMMANDER", "AGGREGATE_OPERATIONS"))
    assert auditor.status_code == 200
    assert sysadmin.status_code == 200
    assert denied.status_code == 403
    # The panel must report real state, not a plausible-looking placeholder.
    governance = auditor.json()["governance"]
    assert governance["auth_method"] == "header_trust"
    assert governance["authenticated"] is False


def test_audit_view_survives_a_corrupt_record() -> None:
    """A truncated final line must not take down the audit view.

    That is exactly the moment an auditor most needs to read the log.
    """
    from pathlib import Path

    from app.api.routes import dashboard as dashboard_module
    from app.security.audit import AuditEvent, AuditLog

    tmp = Path(dashboard_module.AUDIT_PATH).parent / "corrupt_probe.jsonl"
    for leftover in (tmp, Path(f"{tmp}.anchor"), Path(f"{tmp}.key"), Path(f"{tmp}.lock")):
        leftover.unlink(missing_ok=True)
    log = AuditLog(tmp)
    log.append(AuditEvent("T", "AUDITOR", "AUDIT", "ALLOWED", "r", "2026-01-01T00:00:00+00:00", {}))
    try:
        with tmp.open("a", encoding="utf-8") as handle:
            handle.write('{"truncated": ')  # simulate a crash mid-append
        dashboard_module.AUDIT_PATH = tmp
        with TestClient(app) as client:
            response = client.get("/api/dashboard/audit", headers=headers("AUDITOR", "AUDIT"))
        assert response.status_code == 200
        assert response.json()["malformed_records"] == 1
        assert response.json()["event_count"] == 1
        # A corrupt log must be reported as invalid, never as healthy.
        assert response.json()["chain_valid"] is False
        # And appending must refuse rather than overwrite the damaged record.
        import pytest

        with pytest.raises(ValueError, match="refusing to append"):
            AuditLog(tmp).append(
                AuditEvent("T", "AUDITOR", "AUDIT", "ALLOWED", "r", "2026-01-01T00:00:00+00:00", {})
            )
    finally:
        dashboard_module.AUDIT_PATH = _DEFAULT_AUDIT_PATH
        for leftover in (tmp, Path(f"{tmp}.anchor"), Path(f"{tmp}.key"), Path(f"{tmp}.lock")):
            leftover.unlink(missing_ok=True)


def test_dashboard_api_does_not_expose_raw_wellness_columns() -> None:
    with TestClient(app) as client:
        detail = client.get("/api/dashboard/person/P-0001", headers=headers())
    assert detail.status_code == 200
    text = detail.text.lower()
    for forbidden in ("mood_score", "energy_score", "sleep_quality", "perceived_stress", "support_request"):
        assert forbidden not in text


def test_personnel_reports_pagination_truthfully() -> None:
    """A truncated page must be distinguishable from a complete one."""
    with TestClient(app) as client:
        body = client.get("/api/dashboard/personnel?limit=10", headers=headers()).json()
    assert body["count"] == 10
    assert body["total_matching"] == 500
    assert body["truncated"] is True
    # Filter to a subset that fits in one page: now the result is complete and
    # must say so, rather than leaving the client guessing.
    with TestClient(app) as client:
        full = client.get("/api/dashboard/personnel?limit=100&risk_band=HIGH", headers=headers()).json()
    assert full["truncated"] is False
    assert full["count"] == full["total_matching"]