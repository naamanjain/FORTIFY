from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends as FastAPIDepends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.dependencies import require_audit, require_welfare, require_principal
from app.core.paths import AUDIT_PATH
from app.security.principal import Principal
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
    new_state: str = Field(min_length=1, max_length=40)
    reason_code: str = Field(min_length=1, max_length=80)
    # Optimistic concurrency: the client states the state it believes the item is
    # in. If the server has moved on, the transition is rejected instead of
    # silently overwriting a decision made by someone else.
    expected_state: str | None = Field(default=None, max_length=40)


class WorkflowFeedbackRequest(BaseModel):
    helpfulness: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)
    follow_up_requested: bool = False


class WorkflowFollowUpRequest(BaseModel):
    scheduled_for: str = Field(min_length=1, max_length=64)


def _welfare(principal: Principal, resource: str) -> None:
    require_welfare(principal, resource, AUDIT_PATH)


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
    principal: Principal = FastAPIDepends(require_principal),
) -> dict[str, Any]:
    _welfare(principal, "/api/workflow/pending")
    items = _run(lambda: list_items(pending_only=True, limit=limit))
    return {"phase": "Phase 10 — Human-in-the-loop intervention workflow", "items": items, "count": len(items),
            "limit": limit, "truncated": len(items) >= limit,
            "privacy_note": "Workflow output excludes raw wellness/self-report responses."}


@router.get("/follow-ups")
def follow_ups(
    status: str | None = Query(default=None, max_length=20),
    limit: int = Query(default=100, ge=1, le=200),
    principal: Principal = FastAPIDepends(require_principal),
) -> dict[str, Any]:
    _welfare(principal, "/api/workflow/follow-ups")
    items = _run(lambda: list_followups(status=status, limit=limit))
    return {"items": items, "count": len(items),
            "privacy_note": "Follow-up output contains welfare-continuity metadata only."}


@router.post("/follow-ups/{followup_id}/complete")
def complete_follow_up(
    followup_id: str,
    principal: Principal = FastAPIDepends(require_principal),
) -> dict[str, Any]:
    _welfare(principal, f"/api/workflow/follow-ups/{followup_id}/complete")
    return _run(lambda: complete_followup(followup_id, actor_role=principal.role.value, purpose=principal.purpose.value))


@router.get("/{workflow_item_id}")
def detail(workflow_item_id: str, principal: Principal = FastAPIDepends(require_principal)) -> dict[str, Any]:
    _welfare(principal, f"/api/workflow/{workflow_item_id}")
    item = _run(lambda: get_item(workflow_item_id))
    if item is None: raise HTTPException(status_code=404, detail="Workflow item not found")
    item["privacy_note"] = PRIVACY_NOTE
    return item


@router.post("/{workflow_item_id}/transition")
def transition(workflow_item_id: str, payload: WorkflowTransitionRequest,
               principal: Principal = FastAPIDepends(require_principal)) -> dict[str, Any]:
    _welfare(principal, f"/api/workflow/{workflow_item_id}/transition")
    return _run(lambda: transition_item(
        workflow_item_id, new_state=payload.new_state,
        actor_role=principal.role.value, purpose=principal.purpose.value,
        reason_code=payload.reason_code, expected_state=payload.expected_state))


@router.post("/{workflow_item_id}/feedback")
def submit_feedback(workflow_item_id: str, payload: WorkflowFeedbackRequest,
                    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                    principal: Principal = FastAPIDepends(require_principal)) -> dict[str, Any]:
    """Record personnel feedback once.

    Feedback is a welfare outcome measurement, so a duplicated write silently
    corrupts it. An ``Idempotency-Key`` replays the original result; without one
    the service enforces one feedback record per support event at the database
    level.
    """
    _welfare(principal, f"/api/workflow/{workflow_item_id}/feedback")
    if idempotency_key is not None and len(idempotency_key) > 200:
        raise HTTPException(status_code=400, detail="Idempotency-Key is too long")
    return _run(lambda: record_feedback(
        workflow_item_id, helpfulness=payload.helpfulness, comment=payload.comment,
        follow_up_requested=payload.follow_up_requested,
        actor_role=principal.role.value, purpose=principal.purpose.value,
        idempotency_key=idempotency_key))


@router.post("/{workflow_item_id}/follow-up")
def schedule_follow_up(workflow_item_id: str, payload: WorkflowFollowUpRequest,
                       principal: Principal = FastAPIDepends(require_principal)) -> dict[str, Any]:
    _welfare(principal, f"/api/workflow/{workflow_item_id}/follow-up")
    return _run(lambda: schedule_followup(
        workflow_item_id, payload.scheduled_for,
        actor_role=principal.role.value, purpose=principal.purpose.value))


@router.get("/{workflow_item_id}/history")
def history(workflow_item_id: str, principal: Principal = FastAPIDepends(require_principal)) -> dict[str, Any]:
    """Per-case transition history.

    Welfare staff see their own case history; auditors may review history for
    governance. Both require a matching purpose - an auditor's ``AUDIT`` purpose
    alone is not a licence to use the welfare endpoint.
    """
    if principal.purpose.value == "WELFARE_SUPPORT":
        require_welfare(principal, f"/api/workflow/{workflow_item_id}/history", AUDIT_PATH)
    elif principal.purpose.value == "AUDIT":
        require_audit(principal, f"/api/workflow/{workflow_item_id}/history", AUDIT_PATH)
    else:
        raise HTTPException(status_code=403, detail="Workflow history requires welfare-support or audit authorization.")
    item = _run(lambda: get_item(workflow_item_id))
    if item is None: raise HTTPException(status_code=404, detail="Workflow item not found")
    events = item["history"]
    return {"workflow_item_id": workflow_item_id, "events": events, "count": len(events), "privacy_note": PRIVACY_NOTE}