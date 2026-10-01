"""FORTIFY end-to-end workflow lifecycle + negative-case verification.

Run against a live API after `python scripts/build_all.py`:

    uvicorn app.main:app --app-dir backend --port 8000 &
    python scripts/verify_workflow_lifecycle.py

Walks one non-hero workflow item through the complete human-in-the-loop
product flow and asserts that invalid actions, unauthorized actors, and
malformed payloads are rejected.

Exit code 0 when every check passes.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import httpx

BASE_URL = os.getenv("FORTIFY_VERIFY_URL", "http://localhost:8000")
WO, WS = "WELFARE_OFFICER", "WELFARE_SUPPORT"
CMD, AGG = "COMMANDER", "AGGREGATE_OPERATIONS"
AUD, AUDIT = "AUDITOR", "AUDIT"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail and not ok else ""))


def get(path: str, role: str | None = None, purpose: str | None = None) -> httpx.Response:
    headers = {}
    if role:
        headers["X-Fortify-Role"] = role
    if purpose:
        headers["X-Fortify-Purpose"] = purpose
    return httpx.get(f"{BASE_URL}{path}", headers=headers, timeout=60.0)


def post(path: str, role: str, purpose: str, body: dict) -> httpx.Response:
    return httpx.post(f"{BASE_URL}{path}",
                      headers={"X-Fortify-Role": role, "X-Fortify-Purpose": purpose},
                      json=body, timeout=60.0)


def pick_target(states: set[str], min_state: str = "NEW") -> str | None:
    r = get("/api/workflow/pending?limit=200", WO, WS)
    if r.status_code != 200:
        return None
    for item in r.json().get("items", []):
        if item.get("person_id") != "P-0002" and item.get("workflow_state") == min_state:
            return item["workflow_item_id"]
    return None


def main() -> int:
    print(f"Verifying FORTIFY workflow lifecycle against {BASE_URL}\n")

    # 1. Attention queue is reachable for welfare staff.
    pending = get("/api/workflow/pending?limit=50", WO, WS)
    check("L1 attention queue readable (WO+WS)", pending.status_code == 200 and pending.json().get("items"),
          f"status={pending.status_code}")

    # 2. An invalid state name is rejected (400) and does not corrupt the item.
    target = pick_target({"NEW"})
    if target is None:
        print("SKIP: no NEW non-hero workflow item available")
        return 1
    bad = post(f"/api/workflow/{target}/transition", WO, WS,
               {"new_state": "NOT_A_REAL_STATE", "reason_code": "negative test"})
    check("L2 invalid state name rejected", bad.status_code == 400, f"status={bad.status_code}")

    empty = post(f"/api/workflow/{target}/transition", WO, WS,
                 {"new_state": "ACKNOWLEDGED", "reason_code": "   "})
    check("L3 blank reason_code rejected", empty.status_code in (400, 422), f"status={empty.status_code}")

    still = get(f"/api/workflow/{target}", WO, WS).json()
    check("L4 item state unchanged after rejects", still.get("workflow_state") == "NEW",
          f"state={still.get('workflow_state')}")

    # 5. Audit read is denied to welfare purpose; allowed only to auditor.
    denied = get("/api/dashboard/audit", WO, WS)
    check("L5 welfare role cannot read audit view", denied.status_code == 403, f"status={denied.status_code}")

    # 6. Follow-up scheduling before support completion is rejected.
    early = post(f"/api/workflow/{target}/follow-up", WO, WS,
                 {"scheduled_for": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()})
    check("L6 follow-up before support completion rejected", early.status_code == 400,
          f"status={early.status_code}")

    # 7. Feedback before support completion is rejected.
    fb_early = post(f"/api/workflow/{target}/feedback", WO, WS,
                    {"helpfulness": 4, "comment": "negative test", "follow_up_requested": False})
    check("L7 feedback before support completion rejected", fb_early.status_code == 400,
          f"status={fb_early.status_code}")

    # 8. A commander cannot drive the welfare workflow.
    forged = post(f"/api/workflow/{target}/transition", CMD, AGG,
                  {"new_state": "ACKNOWLEDGED", "reason_code": "should be denied"})
    check("L8 commander cannot transition workflow", forged.status_code == 403, f"status={forged.status_code}")

    # 9. Full happy path: NEW -> ACKNOWLEDGED -> IN_REVIEW -> SUPPORT_PLANNED
    ok = True
    for new_state in ("ACKNOWLEDGED", "IN_REVIEW", "SUPPORT_PLANNED"):
        r = post(f"/api/workflow/{target}/transition", WO, WS,
                 {"new_state": new_state, "reason_code": "Lifecycle verification"})
        if r.status_code != 200:
            ok = False
            check(f"L9 transition to {new_state}", False, f"status={r.status_code} {r.text[:120]}")
            break
    if ok:
        check("L9 transitions NEW->ACKNOWLEDGED->IN_REVIEW->SUPPORT_PLANNED", True)

    # 10. Illegal jump (SUPPORT_PLANNED -> IN_REVIEW) is rejected by the state machine.
    illegal = post(f"/api/workflow/{target}/transition", WO, WS,
                   {"new_state": "IN_REVIEW", "reason_code": "illegal regression"})
    check("L10 illegal state regression rejected", illegal.status_code == 400, f"status={illegal.status_code}")

    # 11. Complete support, record personnel feedback, schedule follow-up.
    completed = post(f"/api/workflow/{target}/transition", WO, WS,
                     {"new_state": "SUPPORT_COMPLETED", "reason_code": "Support delivered"})
    check("L11 support completion recorded", completed.status_code == 200, f"status={completed.status_code}")

    fb = post(f"/api/workflow/{target}/feedback", WO, WS,
              {"helpfulness": 5, "comment": "Lifecycle verification", "follow_up_requested": True})
    check("L12 personnel feedback recorded", fb.status_code == 200, f"status={fb.status_code}")

    bad_score = post(f"/api/workflow/{target}/feedback", WO, WS,
                     {"helpfulness": 99, "comment": "out of range", "follow_up_requested": False})
    # Rejected either by Pydantic request validation (422) or the domain guard (400).
    check("L13 out-of-range helpfulness rejected", bad_score.status_code in (400, 422),
          f"status={bad_score.status_code}")

    when = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    fu = post(f"/api/workflow/{target}/follow-up", WO, WS, {"scheduled_for": when})
    check("L14 follow-up scheduled after support", fu.status_code == 200, f"status={fu.status_code}")

    naive = post(f"/api/workflow/{target}/follow-up", WO, WS, {"scheduled_for": "2026-01-01T00:00:00"})
    check("L15 timezone-less follow-up rejected", naive.status_code == 400, f"status={naive.status_code}")

    # 16. Follow-up appears in the follow-ups view and can be closed.
    follow_ups = get("/api/workflow/follow-ups?limit=50", WO, WS)
    fu_ok = follow_ups.status_code == 200 and any(
        i.get("workflow_item_id") == target for i in follow_ups.json().get("items", []))
    check("L16 follow-up visible in follow-ups view", fu_ok, f"status={follow_ups.status_code}")

    item = get(f"/api/workflow/{target}", WO, WS).json()
    fid = item.get("active_followup_id")
    if fid:
        done = post(f"/api/workflow/follow-ups/{fid}/complete", WO, WS, {})
        check("L17 follow-up completion recorded", done.status_code == 200, f"status={done.status_code}")
        closed = post(f"/api/workflow/{target}/transition", WO, WS,
                      {"new_state": "CLOSED", "reason_code": "Outcome recorded"})
        check("L18 workflow closed after follow-up completion", closed.status_code == 200,
              f"status={closed.status_code}")
    else:
        check("L17 follow-up completion recorded", False, "no active follow-up id")

    # 19. Auditor sees the resulting audit trail with a valid chain.
    audit = get("/api/dashboard/audit?limit=100", AUD, AUDIT)
    audit_ok = audit.status_code == 200 and audit.json().get("chain_valid") is True
    check("L19 audit chain still valid after full lifecycle", audit_ok, f"status={audit.status_code}")

    # 20. Unknown workflow item yields 404 rather than a crash.
    missing = get("/api/workflow/WF-does-not-exist", WO, WS)
    check("L20 unknown workflow id returns 404", missing.status_code == 404, f"status={missing.status_code}")

    failed = [(n, d) for n, ok_, d in results if not ok_]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        for name, detail in failed:
            print(f"FAILED: {name} {detail}")
        return 1
    print("FULL WORKFLOW LIFECYCLE VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())