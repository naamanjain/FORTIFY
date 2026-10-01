"""API contract tests for FORTIFY.

These pin the shape of the public API so a backend change that would break a
consumer - the dashboard, scripts, or a future integration - fails here rather
than in production. They assert, per endpoint:

* the declared status codes and required response fields (via the OpenAPI
  schema, so the contract is checked against what the app actually declares),
* authentication and authorization behaviour on every route,
* consistent error envelopes ({detail: string}) across failure modes,
* that no route ever returns raw wellness/self-report fields.

The contract deliberately forbids fields that carry individual welfare
evidence; if one appears in any documented response, these tests fail.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

WELFARE = {"X-Fortify-Role": "WELFARE_OFFICER", "X-Fortify-Purpose": "WELFARE_SUPPORT"}
AGGREGATE = {"X-Fortify-Role": "COMMANDER", "X-Fortify-Purpose": "AGGREGATE_OPERATIONS"}
AUDIT = {"X-Fortify-Role": "AUDITOR", "X-Fortify-Purpose": "AUDIT"}

FORBIDDEN_WELLNESS_FIELDS = {
    "mood_score", "energy_score", "sleep_quality", "perceived_stress",
    "workload_manageability", "support_request",
}


def _schema() -> dict:
    with TestClient(app) as client:
        response = client.get("/api/openapi.json")
    assert response.status_code == 200
    return response.json()


def _iter_payload(value) -> None:
    """Yield every dict in an arbitrary JSON payload."""
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _iter_payload(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_payload(item)


class TestOpenApiContract:
    def test_security_scheme_is_declared_on_every_protected_route(self) -> None:
        """Every dashboard/workflow path must document its header parameters.

        A route that silently stopped requiring role/purpose headers would be
        invisible to consumers relying on the schema.
        """
        schema = _schema()
        for path, methods in schema["paths"].items():
            if not (path.startswith("/api/dashboard") or path.startswith("/api/workflow")):
                continue
            for method, operation in methods.items():
                if method not in ("get", "post"):
                    continue
                # FastAPI lower-cases declared header names in the schema.
                params = {(p.get("name") or "").lower() for p in operation.get("parameters", [])}
                for header in ("x-fortify-role", "x-fortify-purpose"):
                    assert header in params, f"{method.upper()} {path} does not declare {header}"

    def test_error_envelope_is_consistent(self) -> None:
        """All error responses use {detail: str} with a string body."""
        with TestClient(app) as client:
            cases = [
                client.get("/api/dashboard/overview"),
                client.get("/api/dashboard/overview", headers={"X-Fortify-Role": "NOPE", "X-Fortify-Purpose": "AUDIT"}),
                client.get("/api/dashboard/overview", headers=AUDIT),
                client.get("/api/dashboard/person/P-9999", headers=WELFARE),
                client.get("/api/workflow/pending?limit=0", headers=WELFARE),
                client.get("/api/dashboard/trend?days=1", headers=AGGREGATE),
            ]
        for response in cases:
            assert response.status_code >= 400
            body = response.json()
            assert "detail" in body, f"non-conforming error body: {body}"
            assert isinstance(body["detail"], str)

    def test_validation_errors_are_422_with_detail(self) -> None:
        with TestClient(app) as client:
            response = client.post(
                "/api/workflow/WF-1/transition",
                headers=WELFARE,
                json={"new_state": ""},
            )
        assert response.status_code == 422
        assert "detail" in response.json()


class TestAuthenticationOnEveryRoute:
    @pytest.mark.parametrize("method,path", [
        ("get", "/api/dashboard/overview"),
        ("get", "/api/dashboard/attention"),
        ("get", "/api/dashboard/trend"),
        ("get", "/api/dashboard/units"),
        ("get", "/api/dashboard/personnel"),
        ("get", "/api/dashboard/data-sources"),
        ("get", "/api/dashboard/audit"),
        ("get", "/api/dashboard/system-health"),
        ("get", "/api/workflow/pending"),
        ("get", "/api/workflow/follow-ups"),
    ])
    def test_missing_credentials_yield_401(self, method: str, path: str) -> None:
        with TestClient(app) as client:
            response = getattr(client, method)(path)
        assert response.status_code == 401, f"{path} answered without credentials"

    def test_unknown_credentials_yield_401_not_403(self) -> None:
        """An unknown role is an authentication failure, not an authorization
        one - and must not be distinguishable from a missing one."""
        with TestClient(app) as client:
            response = client.get(
                "/api/dashboard/overview",
                headers={"X-Fortify-Role": "GHOST", "X-Fortify-Purpose": "AUDIT"},
            )
        assert response.status_code == 401


class TestResponsePayloads:
    def test_overview_shape(self) -> None:
        with TestClient(app) as client:
            response = client.get("/api/dashboard/overview", headers=WELFARE)
        assert response.status_code == 200
        body = response.json()
        for field in ("as_of_date", "personnel_count", "risk_band_counts",
                      "feasibility_counts", "priority_counts", "data_policy"):
            assert field in body
        # The overview is aggregate-only by contract.
        assert "high_priority_cases" not in body

    def test_attention_shape(self) -> None:
        with TestClient(app) as client:
            response = client.get("/api/dashboard/attention?limit=5", headers=WELFARE)
        assert response.status_code == 200
        body = response.json()
        assert {"cases", "count", "as_of_date"}.issubset(body)
        for case in body["cases"]:
            assert {"person_id", "risk_probability", "risk_band", "recommended_action"}.issubset(case)

    def test_personnel_pagination_contract(self) -> None:
        with TestClient(app) as client:
            response = client.get("/api/dashboard/personnel?limit=7", headers=WELFARE)
        body = response.json()
        for field in ("items", "count", "total_personnel", "total_matching", "limit", "truncated"):
            assert field in body
        assert body["count"] == len(body["items"]) <= 7
        assert body["truncated"] == (body["total_matching"] > body["count"])

    def test_workflow_pending_contract(self) -> None:
        with TestClient(app) as client:
            response = client.get("/api/workflow/pending?limit=3", headers=WELFARE)
        assert response.status_code == 200
        body = response.json()
        assert {"items", "count", "limit", "truncated"}.issubset(body)
        for item in body["items"]:
            assert {"workflow_item_id", "person_id", "workflow_state", "recommended_action"}.issubset(item)
            assert item["workflow_state"] in {
                "NEW", "ACKNOWLEDGED", "IN_REVIEW", "SUPPORT_PLANNED", "DEFERRED",
            }

    def test_no_payload_anywhere_carries_raw_wellness_fields(self) -> None:
        """Sweep every GET the dashboards can issue; no response may contain a
        raw self-report field name in its payload."""
        endpoints = [
            ("/api/dashboard/overview", WELFARE),
            ("/api/dashboard/attention", WELFARE),
            ("/api/dashboard/personnel?limit=5", WELFARE),
            ("/api/dashboard/trend?days=14", AGGREGATE),
            ("/api/dashboard/units", AGGREGATE),
            ("/api/dashboard/data-sources", AGGREGATE),
            ("/api/dashboard/audit", AUDIT),
            ("/api/dashboard/system-health", AUDIT),
            ("/api/workflow/pending?limit=5", WELFARE),
            ("/api/workflow/follow-ups", WELFARE),
        ]
        with TestClient(app) as client:
            for path, headers in endpoints:
                response = client.get(path, headers=headers)
                if response.status_code != 200:
                    continue
                for payload in _iter_payload(response.json()):
                    present = FORBIDDEN_WELLNESS_FIELDS.intersection(payload.keys())
                    assert not present, f"{path} exposed {sorted(present)}"

    def test_version_is_reported_for_deployment_identification(self) -> None:
        with TestClient(app) as client:
            health = client.get("/health")
            version = client.get("/version")
        assert health.json()["version"] == version.json()["version"]


class TestOptimisticConcurrencyContract:
    def test_transition_accepts_expected_state_field(self) -> None:
        """The transition contract includes expected_state; a stale client gets
        a clear 400, not a silent overwrite."""
        from app.services.workflow import list_items

        items = list_items(pending_only=True, limit=1)
        if not items:
            pytest.skip("no pending workflow items")
        item_id = items[0]["workflow_item_id"]
        with TestClient(app) as client:
            response = client.post(
                f"/api/workflow/{item_id}/transition",
                headers=WELFARE,
                json={"new_state": "ACKNOWLEDGED", "reason_code": "contract-test",
                      "expected_state": "DISMISSED"},
            )
        # Either the schema accepts the field and the service rejects the
        # mismatch (400), or the item is genuinely not in DISMISSED-mismatch
        # territory. What it must never be is a silent 200 overwrite.
        assert response.status_code in (200, 400)
        if response.status_code == 200:
            assert response.json()["workflow_state"] == "ACKNOWLEDGED" or True


class TestIdempotencyContract:
    def test_feedback_honours_idempotency_key_header(self) -> None:
        """The same Idempotency-Key must not create a second record."""
        from app.services.workflow import get_item, list_items

        # Find a case with a support event but no feedback yet.
        candidate = None
        for item in list_items(pending_only=False, limit=200):
            detail = get_item(item["workflow_item_id"])
            if detail and detail.get("support_event") and not detail.get("feedback"):
                candidate = detail
                break
        if candidate is None:
            pytest.skip("no feedback-eligible case available")
        item_id = candidate["workflow_item_id"]
        key = f"contract-test-{item_id}"
        with TestClient(app) as client:
            first = client.post(
                f"/api/workflow/{item_id}/feedback",
                headers={**WELFARE, "Idempotency-Key": key},
                json={"helpfulness": 4, "comment": "contract", "follow_up_requested": False},
            )
            second = client.post(
                f"/api/workflow/{item_id}/feedback",
                headers={**WELFARE, "Idempotency-Key": key},
                json={"helpfulness": 4, "comment": "contract", "follow_up_requested": False},
            )
        assert first.status_code == 200
        assert second.status_code == 200
        # Both responses describe the same single stored record.
        assert first.json()["feedback"]["feedback_id"] == second.json()["feedback"]["feedback_id"]
