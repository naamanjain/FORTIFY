from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Any

from app.core.paths import AUDIT_PATH
from app.security.audit import AuditEvent, AuditLog
from app.security.rbac import authorize
from app.security.security_config import AccessPurpose, SecurityRole
from app.services.workflow import (
    DataUnavailable,
    complete_followup,
    get_item,
    list_followups,
    list_items,
    record_feedback,
    schedule_followup,
    transition_item,
)

router = APIRouter(prefix="/api/workflow", tags=["workflow"])


class WorkflowTransitionRequest(BaseModel):
    new_state: str = Field(min_length=1)
    reason_code: str = Field(min_length=1, max_length=80)


class WorkflowFeedbackRequest(BaseModel):
    helpfulness: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)
    follow_up_requested: bool = False


class WorkflowFollowUpRequest(BaseModel):
    scheduled_for: str = Field(min_length=1)


def _security(role: str | None, purpose: str | None, resource: str) -> tuple[str, str]:
    if not role or not purpose:
        raise HTTPException(status_code=401, detail="Workflow requires role and purpose headers in the prototype.")
    decision = authorize(role, purpose)
    AuditLog(AUDIT_PATH).append(AuditEvent(
        "WORKFLOW_ACCESS", role, purpose, "ALLOWED" if decision.allowed else "DENIED", resource,
        _utc_now(), {"policy_version": decision.policy_version}))
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)
    return role, purpose


def _require_welfare(role: str, purpose: str, resource: str) -> None:
    if role != SecurityRole.WELFARE_OFFICER.value or purpose != AccessPurpose.WELFARE_SUPPORT.value:
        AuditLog(AUDIT_PATH).append(AuditEvent(
            "WORKFLOW_ACCESS", role, purpose, "DENIED", resource,
            _utc_now(), {"reason": "Individual workflow access requires welfare-support authorization."}))
        raise HTTPException(status_code=403, detail="Individual workflow access requires welfare-support authorization.")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(call: Any) -> Any:
    """Map expected service-level failures to HTTP responses."""
    try:
        return call()
    except DataUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc.args[0] if exc.args else str(exc))) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0] if exc.args else exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


PRIVACY_NOTE = "Raw wellness/self-report responses are not exposed."


@router.get("/pending")
def pending(
    limit: int = Query(default=50, ge=1, le=200),
    x_fortify_role: str | None = Header(default=None),
    x_fortify_purpose: str | None = Header(default=None),
) -> dict[str, Any]:
    role, purpose = _security(x_fortify_role, x_fortify_purpose, "/api/workflow/pending")
    _require_welfare(role, purpose, "/api/workflow/pending")
    items = _run(lambda: list_items(pending_only=True, limit=limit))
    return {"phase": "Phase 10 — Human-in-the-loop intervention workflow", "items": items, "count": len(items),
            "privacy_note": "Workflow output excludes raw wellness/self-report responses."}


@router.get("/follow-ups")
def follow_ups(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    x_fortify_role: str | None = Header(default=None),
    x_fortify_purpose: str | None = Header(default=None),
) -> dict[str, Any]:
    role, purpose = _security(x_fortify_role, x_fortify_purpose, "/api/workflow/follow-ups")
    _require_welfare(role, purpose, "/api/workflow/follow-ups")
    items = _run(lambda: list_followups(status=status, limit=limit))
    return {"items": items, "count": len(items),
            "privacy_note": "Follow-up output contains welfare-continuity metadata only."}


@router.post("/follow-ups/{followup_id}/complete")
def complete_follow_up(
    followup_id: str,
    x_fortify_role: str | None = Header(default=None),
    x_fortify_purpose: str | None = Header(default=None),
) -> dict[str, Any]:
    role, purpose = _security(x_fortify_role, x_fortify_purpose, f"/api/workflow/follow-ups/{followup_id}/complete")
    _require_welfare(role, purpose, f"/api/workflow/follow-ups/{followup_id}/complete")
    return _run(lambda: complete_followup(followup_id, actor_role=role, purpose=purpose))


@router.get("/{workflow_item_id}")
def detail(workflow_item_id: str, x_fortify_role: str | None = Header(default=None), x_fortify_purpose: str | None = Header(default=None)) -> dict[str, Any]:
    role, purpose = _security(x_fortify_role, x_fortify_purpose, f"/api/workflow/{workflow_item_id}")
    _require_welfare(role, purpose, f"/api/workflow/{workflow_item_id}")
    item = _run(lambda: get_item(workflow_item_id))
    if item is None: raise HTTPException(status_code=404, detail="Workflow item not found")
    item["privacy_note"] = PRIVACY_NOTE
    return item


@router.post("/{workflow_item_id}/transition")
def transition(workflow_item_id: str, payload: WorkflowTransitionRequest,
               x_fortify_role: str | None = Header(default=None), x_fortify_purpose: str | None = Header(default=None)) -> dict[str, Any]:
    role, purpose = _security(x_fortify_role, x_fortify_purpose, f"/api/workflow/{workflow_item_id}/transition")
    return _run(lambda: transition_item(
        workflow_item_id, new_state=payload.new_state, actor_role=role, purpose=purpose, reason_code=payload.reason_code))


@router.post("/{workflow_item_id}/feedback")
def submit_feedback(workflow_item_id: str, payload: WorkflowFeedbackRequest,
                    x_fortify_role: str | None = Header(default=None), x_fortify_purpose: str | None = Header(default=None)) -> dict[str, Any]:
    role, purpose = _security(x_fortify_role, x_fortify_purpose, f"/api/workflow/{workflow_item_id}/feedback")
    _require_welfare(role, purpose, f"/api/workflow/{workflow_item_id}/feedback")
    return _run(lambda: record_feedback(
        workflow_item_id, helpfulness=payload.helpfulness, comment=payload.comment,
        follow_up_requested=payload.follow_up_requested, actor_role=role, purpose=purpose))


@router.post("/{workflow_item_id}/follow-up")
def schedule_follow_up(workflow_item_id: str, payload: WorkflowFollowUpRequest,
                       x_fortify_role: str | None = Header(default=None), x_fortify_purpose: str | None = Header(default=None)) -> dict[str, Any]:
    role, purpose = _security(x_fortify_role, x_fortify_purpose, f"/api/workflow/{workflow_item_id}/follow-up")
    _require_welfare(role, purpose, f"/api/workflow/{workflow_item_id}/follow-up")
    return _run(lambda: schedule_followup(workflow_item_id, payload.scheduled_for, actor_role=role, purpose=purpose))


@router.get("/{workflow_item_id}/history")
def history(workflow_item_id: str, x_fortify_role: str | None = Header(default=None), x_fortify_purpose: str | None = Header(default=None)) -> dict[str, Any]:
    role, purpose = _security(x_fortify_role, x_fortify_purpose, f"/api/workflow/{workflow_item_id}/history")
    if role not in {SecurityRole.WELFARE_OFFICER.value, SecurityRole.AUDITOR.value}:
        AuditLog(AUDIT_PATH).append(AuditEvent(
            "WORKFLOW_ACCESS", role, purpose, "DENIED", f"/api/workflow/{workflow_item_id}/history",
            _utc_now(), {"reason": "Workflow history is restricted to authorized welfare or audit access."}))
        raise HTTPException(status_code=403, detail="Workflow history is restricted to authorized welfare or audit access.")
    item = _run(lambda: get_item(workflow_item_id))
    if item is None: raise HTTPException(status_code=404, detail="Workflow item not found")
    events = item["history"]
    return {"workflow_item_id": workflow_item_id, "events": events, "count": len(events), "privacy_note": PRIVACY_NOTE}
