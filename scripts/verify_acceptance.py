"""FORTIFY acceptance verification — API smoke, scenarios A-J, security attempts.

Run against a live API (default http://localhost:8000) after
`python scripts/build_all.py` has populated the demo environment:

    uvicorn app.main:app --app-dir backend --port 8000 &
    python scripts/verify_acceptance.py

Scenarios:
  A  Health endpoint responds 200 with the FORTIFY service payload.
  B  Welfare officer reads the aggregate dashboard overview.
  C  Commander reads aggregate unit summaries (aggregate-first, no person list).
  D  Welfare officer opens an individual person profile (P-0002 hero case).
  E  Commander is DENIED individual person detail (aggregate-only role).
  F  Welfare officer performs audited workflow transitions (non-hero item).
  G  Auditor reads the audit view with a valid hash chain.
  H  Workflow transition with the wrong purpose is DENIED.
  I  Auditor is DENIED individual welfare data.
  J  Administrator reads system health; trend endpoint serves points.

Security attempts:
  S1  Missing role/purpose headers are rejected (401).
  S2  Forged/unknown role is rejected (403).
  S3  Role/purpose mismatch on the audit endpoint is rejected (403).
  S4  No raw wellness/self-report field appears in any successful payload.

Exit code 0 when every scenario and attempt passes.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx

BASE_URL = os.getenv("FORTIFY_VERIFY_URL", "http://localhost:8000")

WO, WS = "WELFARE_OFFICER", "WELFARE_SUPPORT"
CMD, AGG = "COMMANDER", "AGGREGATE_OPERATIONS"
AUD, AUDIT = "AUDITOR", "AUDIT"
ADM, INFRA = "SYSTEM_ADMINISTRATOR", "INFRASTRUCTURE_ADMIN"

FORBIDDEN_RAW_FIELDS = {
    "mood_score", "energy_score", "sleep_quality", "perceived_stress",
    "workload_manageability", "support_request",
}

results: list[tuple[str, bool, str]] = []
payloads: list[Any] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail and not ok else ""))


def get(path: str, role: str | None, purpose: str | None) -> httpx.Response:
    headers = {}
    if role is not None:
        headers["X-Fortify-Role"] = role
    if purpose is not None:
        headers["X-Fortify-Purpose"] = purpose
    return httpx.get(f"{BASE_URL}{path}", headers=headers, timeout=60.0)


def post(path: str, role: str, purpose: str, body: dict[str, Any]) -> httpx.Response:
    return httpx.post(
        f"{BASE_URL}{path}",
        headers={"X-Fortify-Role": role, "X-Fortify-Purpose": purpose},
        json=body,
        timeout=60.0,
    )


def scan_forbidden(node: Any, path: str = "") -> list[str]:
    """Recursively collect any raw wellness/self-report keys in a payload."""
    hits: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            if str(key) in FORBIDDEN_RAW_FIELDS:
                hits.append(here)
            hits.extend(scan_forbidden(value, here))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            hits.extend(scan_forbidden(item, f"{path}[{index}]"))
    return hits


def scenario_a() -> None:
    r = get("/health", None, None)
    ok = r.status_code == 200 and r.json().get("service") == "FORTIFY"
    check("A  health endpoint", ok, f"status={r.status_code} body={r.text[:120]}")


def scenario_b() -> None:
    r = get("/api/dashboard/overview", WO, WS)
    ok = r.status_code == 200
    if ok:
        body = r.json()
        payloads.append(body)
        ok = len(scan_forbidden(body)) == 0
    check("B  welfare overview (WO+WS)", ok, f"status={r.status_code}")


def scenario_c() -> None:
    r = get("/api/dashboard/units", CMD, AGG)
    ok = r.status_code == 200
    if ok:
        body = r.json()
        payloads.append(body)
        text = json.dumps(body)
        ok = "P-0002" not in text and len(scan_forbidden(body)) == 0
    check("C  commander unit aggregates (aggregate-first)", ok, f"status={r.status_code}")


def scenario_d() -> None:
    r = get("/api/dashboard/person/P-0002", WO, WS)
    ok = r.status_code == 200
    if ok:
        body = r.json()
        payloads.append(body)
        ok = len(scan_forbidden(body)) == 0
    check("D  welfare person detail P-0002 (WO+WS)", ok, f"status={r.status_code}")


def scenario_e() -> None:
    r = get("/api/dashboard/person/P-0002", CMD, AGG)
    check("E  commander denied person detail", r.status_code == 403, f"status={r.status_code}")


def scenario_f() -> None:
    r = get("/api/workflow/pending?limit=50", WO, WS)
    if r.status_code != 200:
        check("F  workflow lifecycle", False, f"pending status={r.status_code}")
        return
    items = r.json().get("items", [])
    payloads.append(r.json())
    target = next(
        (i for i in items if i.get("person_id") != "P-0002" and i.get("workflow_state") == "NEW"),
        None,
    )
    if target is None:
        check("F  workflow lifecycle", False, "no NEW non-hero item available")
        return
    item_id = target["workflow_item_id"]

    t1 = post(f"/api/workflow/{item_id}/transition", WO, WS,
              {"new_state": "ACKNOWLEDGED", "reason_code": "Acceptance verification A-J"})
    if t1.status_code != 200:
        check("F  workflow lifecycle", False, f"transition-1 status={t1.status_code} {t1.text[:160]}")
        return
    payloads.append(t1.json())
    t2 = post(f"/api/workflow/{item_id}/transition", WO, WS,
              {"new_state": "IN_REVIEW", "reason_code": "Acceptance verification A-J"})
    if t2.status_code != 200:
        check("F  workflow lifecycle", False, f"transition-2 status={t2.status_code} {t2.text[:160]}")
        return
    payloads.append(t2.json())

    item = get(f"/api/workflow/{item_id}", WO, WS).json()
    payloads.append(item)
    ok = item.get("workflow_state") == "IN_REVIEW" and len(scan_forbidden(item)) == 0
    check("F  workflow lifecycle (NEW→ACKNOWLEDGED→IN_REVIEW, audited)", ok,
          f"final state={item.get('workflow_state')}")


def scenario_g() -> None:
    r = get("/api/dashboard/audit", AUD, AUDIT)
    ok = r.status_code == 200
    if ok:
        body = r.json()
        payloads.append(body)
        ok = body.get("chain_valid") is True and body.get("event_count", 0) > 0
    check("G  auditor audit view with valid hash chain", ok, f"status={r.status_code}")


def scenario_h() -> None:
    r = get("/api/workflow/pending?limit=5", WO, WS)
    items = r.json().get("items", []) if r.status_code == 200 else []
    if not items:
        check("H  wrong-purpose transition denied", False, "no pending items to attempt")
        return
    item_id = items[0]["workflow_item_id"]
    resp = post(f"/api/workflow/{item_id}/transition", WO, AGG,
                {"new_state": "ACKNOWLEDGED", "reason_code": "Should be denied"})
    check("H  workflow transition with wrong purpose denied", resp.status_code == 403,
          f"status={resp.status_code}")


def scenario_i() -> None:
    r = get("/api/dashboard/person/P-0002", AUD, AUDIT)
    check("I  auditor denied individual welfare data", r.status_code == 403, f"status={r.status_code}")


def scenario_j() -> None:
    r1 = get("/api/dashboard/system-health", ADM, INFRA)
    # Trend is an aggregate view: it requires the aggregate-operations purpose,
    # from any role holding that purpose. Welfare purpose is correctly refused.
    r2 = get("/api/dashboard/trend?days=30", WO, AGG)
    r3 = get("/api/dashboard/trend?days=30", WO, WS)
    ok = r1.status_code == 200 and r2.status_code == 200 and r3.status_code == 403
    if ok:
        payloads.append(r1.json())
        body = r2.json()
        payloads.append(body)
        ok = len(body.get("points", [])) > 0 and len(scan_forbidden(body)) == 0
    check("J  system health (admin) + trend (aggregate) + trend (welfare denied)", ok,
          f"health={r1.status_code} trend={r2.status_code} welfare-trend={r3.status_code}")


def security_attempts() -> None:
    r = get("/api/dashboard/overview", None, None)
    check("S1 missing headers rejected", r.status_code == 401, f"status={r.status_code}")

    r = get("/api/dashboard/overview", "SUPERADMIN", WS)
    # An unknown role is an authentication failure (401), not an authorization
    # failure (403): the principal cannot even be constructed.
    check("S2 forged role rejected", r.status_code == 401, f"status={r.status_code}")

    r = get("/api/dashboard/audit", WO, AUDIT)
    check("S3 role/purpose mismatch on audit rejected", r.status_code == 403,
          f"status={r.status_code}")

    leak = [hit for payload in payloads for hit in scan_forbidden(payload)]
    check("S4 no raw wellness fields in any payload", not leak, f"leaked keys: {leak[:5]}")


def main() -> int:
    print(f"Verifying FORTIFY acceptance scenarios against {BASE_URL}\n")
    scenario_a()
    scenario_b()
    scenario_c()
    scenario_d()
    scenario_e()
    scenario_f()
    scenario_g()
    scenario_h()
    scenario_i()
    scenario_j()
    security_attempts()

    failed = [(n, d) for n, ok, d in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        for name, detail in failed:
            print(f"FAILED: {name} {detail}")
        return 1
    print("ALL SCENARIOS AND SECURITY ATTEMPTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
