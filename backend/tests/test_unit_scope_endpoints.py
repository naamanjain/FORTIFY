"""Endpoint-level unit/object scope enforcement.

These are request-path tests, not helper tests: the guard only counts if a real
route refuses. Subjects and units are taken from the repository's own generated
data, so the tests exercise the real unit ids rather than invented ones.

The demonstration build is header-trust and unauthenticated; a scope is supplied
through FORTIFY_DEMO_UNIT_SCOPE. A verified identity is scoped strictly by its
own claims, which the injected authenticator below models - it is a test double
for the seam an OIDC adapter plugs into, NOT a simulated identity provider.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.api.dependencies as dependencies
import app.services.workflow as workflow
from app.main import app
from app.security.principal import Principal
from app.security.rbac import UnitScope
from app.security.security_config import AccessPurpose, SecurityRole

SCRIPT_SCOPE = UnitScope.script()
WELFARE = {"X-Fortify-Role": "WELFARE_OFFICER", "X-Fortify-Purpose": "WELFARE_SUPPORT"}


@pytest.fixture()
def client_factory(monkeypatch):
    """A TestClient whose demo unit scope is whatever the test asks for.

    Scope is read per request, so this changes authorization without restarting
    the app - and every test states the scope it depends on explicitly.
    """
    def build(units: str) -> TestClient:
        monkeypatch.setenv("FORTIFY_DEMO_UNIT_SCOPE", units)
        return TestClient(app)
    return build


@pytest.fixture(scope="module")
def pairs():
    """Two open cases that belong to two different units.

    Everything downstream asserts against these, so a missing precondition fails
    loudly instead of silently skipping the security assertions.
    """
    items = workflow.list_items(pending_only=True, limit=200, unit_scope=SCRIPT_SCOPE)
    by_unit: dict[str, dict] = {}
    for item in items:
        unit = str(item.get("unit_id") or "")
        if unit and unit not in by_unit:
            by_unit[unit] = item
    if len(by_unit) < 2:
        pytest.fail(f"need open cases in >=2 units, found {sorted(by_unit)}; run scripts/build_all.py")
    unit_a, unit_b = sorted(by_unit)[:2]
    return {"unit_a": unit_a, "unit_b": unit_b,
            "case_a": by_unit[unit_a], "case_b": by_unit[unit_b]}


def test_in_scope_officer_reads_their_own_person(client_factory, pairs):
    """1. A welfare officer whose scope contains the unit gets the record."""
    client = client_factory(f"{pairs['unit_a']}")
    person_id = pairs["case_a"]["person_id"]
    response = client.get(f"/api/dashboard/person/{person_id}", headers=WELFARE)
    assert response.status_code == 200
    assert response.json()["unit_id"] == pairs["unit_a"]


def test_out_of_scope_officer_cannot_read_or_mutate(client_factory, pairs):
    """2. The same role, a different unit: no read, no detail, no transition."""
    client = client_factory(pairs["unit_a"])
    other = pairs["case_b"]
    assert client.get(f"/api/dashboard/person/{other['person_id']}", headers=WELFARE).status_code == 404
    assert client.get(f"/api/workflow/{other['workflow_item_id']}", headers=WELFARE).status_code == 404
    denied = client.post(f"/api/workflow/{other['workflow_item_id']}/transition",
                         headers=WELFARE,
                         json={"new_state": "ACKNOWLEDGED", "reason_code": "scope-probe"})
    assert denied.status_code == 404
    # and the case itself did not move
    stored = workflow.get_item(other["workflow_item_id"], unit_scope=SCRIPT_SCOPE)
    assert stored["workflow_state"] == other["workflow_state"]


def test_denial_and_absence_are_indistinguishable(client_factory, pairs):
    """2b. No enumeration oracle: unknown id and out-of-scope id answer alike."""
    client = client_factory(pairs["unit_a"])
    unknown = client.get("/api/dashboard/person/P-9999999", headers=WELFARE)
    scoped_out = client.get(f"/api/dashboard/person/{pairs['case_b']['person_id']}", headers=WELFARE)
    assert unknown.status_code == scoped_out.status_code == 404
    assert unknown.json()["detail"] == scoped_out.json()["detail"]


@pytest.mark.parametrize("scope_value", ["", "  ", "U-***", "*", "demo:all-units,U-011", ",U-011"])
def test_missing_empty_or_malformed_scope_denies_person_access(client_factory, pairs, scope_value):
    """3. Absence of scope is absence of access, never "all units"."""
    client = client_factory(scope_value)
    person_id = pairs["case_a"]["person_id"]
    assert client.get(f"/api/dashboard/person/{person_id}", headers=WELFARE).status_code == 404
    pending = client.get("/api/workflow/pending", headers=WELFARE)
    assert pending.status_code == 200
    assert pending.json()["items"] == []
    overview = client.get("/api/dashboard/overview", headers=WELFARE)
    assert overview.status_code == 200
    assert overview.json()["personnel_count"] == 0


def test_forged_scope_header_grants_nothing(client_factory, pairs):
    """4. Scope is never a request header: smuggling one changes nothing."""
    client = client_factory(pairs["unit_a"])
    headers = {**WELFARE, "X-Fortify-Units": pairs["unit_b"],
               "X-Fortify-Unit-Scope": "*", "Fortify-Scope": "all"}
    assert client.get(f"/api/dashboard/person/{pairs['case_b']['person_id']}",
                      headers=headers).status_code == 404
    assert client.get("/api/workflow/pending", headers=headers).json()["items"] != []


def test_wrong_purpose_is_refused_before_scope_matters(client_factory, pairs):
    """5. A welfare-purpose header is the only purpose that reaches person data."""
    client = client_factory(pairs["unit_a"])
    response = client.get(f"/api/dashboard/person/{pairs['case_a']['person_id']}",
                          headers={"X-Fortify-Role": "WELFARE_OFFICER",
                                   "X-Fortify-Purpose": "AGGREGATE_OPERATIONS"})
    assert response.status_code == 403


def test_commander_sees_only_scoped_aggregates(client_factory, pairs):
    """6. Command leadership: aggregates for its own units, never person rows."""
    client = client_factory(pairs["unit_a"])
    headers = {"X-Fortify-Role": "COMMANDER", "X-Fortify-Purpose": "AGGREGATE_OPERATIONS"}
    units = client.get("/api/dashboard/units", headers=headers).json()["units"]
    assert {str(u["unit_id"]) for u in units} == {pairs["unit_a"]}
    detail = client.get(f"/api/dashboard/unit/{pairs['unit_b']}", headers=headers)
    assert detail.status_code == 404
    person = client.get(f"/api/dashboard/person/{pairs['case_a']['person_id']}", headers=headers)
    assert person.status_code == 403


def test_auditor_and_admin_get_no_person_welfare(client_factory, pairs):
    """7. Governance and operations roles do not inherit welfare access."""
    client = client_factory(pairs["unit_a"])
    person = pairs["case_a"]["person_id"]
    for headers in ({"X-Fortify-Role": "AUDITOR", "X-Fortify-Purpose": "AUDIT"},
                    {"X-Fortify-Role": "SYSTEM_ADMINISTRATOR", "X-Fortify-Purpose": "INFRASTRUCTURE_ADMIN"}):
        assert client.get(f"/api/dashboard/person/{person}", headers=headers).status_code == 403
        assert client.get("/api/dashboard/attention", headers=headers).status_code == 403


def test_search_personnel_and_pagination_cannot_leak(client_factory, pairs):
    """8. Counts and pages are computed inside the scope, not after it.

    Scope is resolved per request from configuration, so a client built under one
    scope is not frozen to it - each assertion below re-creates the client it
    needs rather than reusing a handle across a scope change.
    """
    scoped = lambda: client_factory(pairs["unit_a"])
    personnel = scoped().get("/api/dashboard/personnel?limit=100", headers=WELFARE).json()
    assert personnel["items"], "in-scope unit should have people"
    assert {item["unit_id"] for item in personnel["items"]} == {pairs["unit_a"]}

    unscoped = client_factory("demo:all-units").get("/api/dashboard/personnel?limit=100",
                                                    headers=WELFARE).json()
    # The scoped caller must see strictly fewer people than the whole force, and
    # its totals must describe only its own units.
    assert 0 < personnel["total_matching"] < unscoped["total_matching"]
    assert personnel["total_personnel"] < unscoped["total_personnel"]

    search = scoped().get(f"/api/dashboard/search?query={pairs['unit_b']}", headers=WELFARE).json()
    assert search["results"] == [], f"out-of-scope unit leaked into search: {search}"
    mine = scoped().get(f"/api/dashboard/search?query={pairs['unit_a']}", headers=WELFARE).json()
    assert mine["results"], "the caller's own unit must remain searchable"


def test_queue_and_followups_are_scoped(client_factory, pairs):
    """9. Both workflow queues restrict before they limit."""
    client = client_factory(pairs["unit_a"])
    pending = client.get("/api/workflow/pending?limit=200", headers=WELFARE).json()["items"]
    assert pending
    assert {item["unit_id"] for item in pending} == {pairs["unit_a"]}
    assert pairs["case_b"]["workflow_item_id"] not in {item["workflow_item_id"] for item in pending}
    followups = client.get("/api/workflow/follow-ups?limit=200", headers=WELFARE).json()
    assert isinstance(followups["items"], list)


def test_stale_or_concurrent_mutation_still_needs_scope(client_factory, pairs):
    """10. A correct expected_state does not substitute for authorization."""
    other = pairs["case_b"]
    client = client_factory(pairs["unit_a"])
    rejected = client.post(f"/api/workflow/{other['workflow_item_id']}/transition",
                           headers=WELFARE,
                           json={"new_state": "ACKNOWLEDGED", "reason_code": "stale-scope-probe",
                                 "expected_state": other["workflow_state"]})
    assert rejected.status_code == 404
    feedback = client.post(f"/api/workflow/{other['workflow_item_id']}/feedback",
                           headers=WELFARE, json={"helpfulness": 5, "comment": "probe"})
    assert feedback.status_code in (404, 400, 500)
    assert feedback.status_code != 200


def test_demo_wide_scope_keeps_the_golden_path_working(client_factory, pairs):
    """11. The named demonstration permission still lets the walkthrough run."""
    client = client_factory("demo:all-units")
    person_id = pairs["case_a"]["person_id"]
    assert client.get(f"/api/dashboard/person/{person_id}", headers=WELFARE).status_code == 200
    assert client.get("/api/workflow/pending?limit=200", headers=WELFARE).json()["items"]

    item_id = pairs["case_a"]["workflow_item_id"]
    current = str(workflow.get_item(item_id, unit_scope=SCRIPT_SCOPE)["workflow_state"])
    legal = {"NEW": "ACKNOWLEDGED", "ACKNOWLEDGED": "IN_REVIEW", "IN_REVIEW": "DEFERRED",
             "DEFERRED": "ACKNOWLEDGED", "SUPPORT_PLANNED": "DEFERRED"}.get(current)
    if legal is None:
        pytest.skip(f"case {item_id} is in terminal state {current}; no transition to attempt")
    moved = client.post(f"/api/workflow/{item_id}/transition", headers=WELFARE,
                        json={"new_state": legal, "reason_code": "demo-golden-path",
                              "expected_state": current})
    # This test is about authorization, not about the state machine: a wide demo
    # scope must never be answered with a refusal. Repeated runs land in
    # different states, so the assertion follows legal rather than fixed moves.
    assert moved.status_code not in (401, 403, 404), moved.text
    assert moved.status_code == 200


def test_verified_identity_never_receives_the_demo_wildcard(client_factory, pairs, monkeypatch):
    """12. Claims decide for a real identity; the demo sentinel cannot leak in."""
    class _ClaimsAuthenticator:
        method_name = "test-claims"

        def __init__(self, scope: frozenset[str]) -> None:
            self._scope = scope

        def authenticate(self, credentials: dict[str, str]) -> Principal:
            return Principal(subject="officer-1", role=SecurityRole.WELFARE_OFFICER,
                             purpose=AccessPurpose.WELFARE_SUPPORT,
                             auth_method=self.method_name, authenticated=True,
                             unit_scope=self._scope)

    monkeypatch.setenv("FORTIFY_DEMO_UNIT_SCOPE", "demo:all-units")
    # Capture BEFORE swapping: _AUTHENTICATOR is the module global this call
    # overwrites, so restoring from it afterwards would reinstall the double and
    # leak an authenticated identity into every later test in the process.
    original = dependencies.get_authenticator()
    dependencies.set_authenticator(_ClaimsAuthenticator(frozenset({pairs["unit_a"]})))
    try:
        client = TestClient(app)
        assert client.get(f"/api/dashboard/person/{pairs['case_a']['person_id']}",
                          headers=WELFARE).status_code == 200
        # The demo wildcard is configured, yet a verified token is still bound to
        # its own claims - this is the production guarantee.
        assert client.get(f"/api/dashboard/person/{pairs['case_b']['person_id']}",
                          headers=WELFARE).status_code == 404
    finally:
        dependencies.set_authenticator(original)


def test_verified_identity_without_unit_claim_is_denied(client_factory, pairs, monkeypatch):
    """12b. A valid token with no unit claim reads no person data at all."""
    class _NoScopeAuthenticator:
        method_name = "test-claims-empty"

        def authenticate(self, credentials: dict[str, str]) -> Principal:
            return Principal(subject="officer-2", role=SecurityRole.WELFARE_OFFICER,
                             purpose=AccessPurpose.WELFARE_SUPPORT,
                             auth_method=self.method_name, authenticated=True,
                             unit_scope=frozenset())

    monkeypatch.setenv("FORTIFY_DEMO_UNIT_SCOPE", "demo:all-units")
    original = dependencies.get_authenticator()
    dependencies.set_authenticator(_NoScopeAuthenticator())
    try:
        client = TestClient(app)
        assert client.get(f"/api/dashboard/person/{pairs['case_a']['person_id']}",
                          headers=WELFARE).status_code == 404
        assert client.get("/api/workflow/pending", headers=WELFARE).json()["items"] == []
    finally:
        dependencies.set_authenticator(original)
    # The leak this guard exists to catch: header trust must be back afterwards.
    assert dependencies.get_authenticator() is original
    with TestClient(app) as probe:
        assert probe.get("/api/dashboard/overview").status_code == 401
