from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import os

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.security.audit import AuditEvent, AuditLog
from app.security.rbac import authorize
from app.security.security_config import AccessPurpose, SecurityRole
from app.services.workflow import get_history, get_item, list_items, transition_item

router = APIRouter(prefix="/api/workflow", tags=["workflow"])
ROOT = Path(__file__).resolve().parents[4]
AUDIT_PATH = Path(os.getenv("FORTIFY_AUDIT_LOG", ROOT / "artifacts" / "phase8" / "dashboard_audit.jsonl"))


class WorkflowTransitionRequest(BaseModel):
    new_state: str = Field(min_length=1)
    reason_code: str = Field(min_length=1, max_length=80)


def _security(role: str | None, purpose: str | None, resource: str) -> tuple[str, str]:
    if not role or not purpose:
        raise HTTPException(status_code=401, detail="Workflow requires role and purpose headers in the prototype.")
    decision = authorize(role, purpose)
    AuditLog(AUDIT_PATH).append(AuditEvent(
        "WORKFLOW_ACCESS", role, purpose, "ALLOWED" if decision.allowed else "DENIED", resource,
        datetime.now(timezone.utc).isoformat(), {"policy_version": decision.policy_version}))
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)
    return role, purpose


def _require_welfare(role: str, purpose: str) -> None:
    if role != SecurityRole.WELFARE_OFFICER.value or purpose != AccessPurpose.WELFARE_SUPPORT.value:
        raise HTTPException(status_code=403, detail="Individual workflow access requires welfare-support authorization.")


@router.get("/pending")
def pending(
    limit: int = Query(default=50, ge=1, le=200),
    x_fortify_role: str | None = Header(default=None),
    x_fortify_purpose: str | None = Header(default=None),
) -> dict[str, Any]:
    role, purpose = _security(x_fortify_role, x_fortify_purpose, "/api/workflow/pending")
    _require_welfare(role, purpose)
    items = list_items(pending_only=True, limit=limit)
    return {"phase": "Phase 10 — Human-in-the-loop intervention workflow", "items": items, "count": len(items),
            "privacy_note": "Workflow output excludes raw wellness/self-report responses."}


@router.get("/{workflow_item_id}")
def detail(workflow_item_id: str, x_fortify_role: str | None = Header(default=None), x_fortify_purpose: str | None = Header(default=None)) -> dict[str, Any]:
    role, purpose = _security(x_fortify_role, x_fortify_purpose, f"/api/workflow/{workflow_item_id}")
    _require_welfare(role, purpose)
    item = get_item(workflow_item_id)
    if item is None: raise HTTPException(status_code=404, detail="Workflow item not found")
    item["history"] = get_history(workflow_item_id)
    item["privacy_note"] = "Raw wellness/self-report responses are not exposed."
    return item


@router.post("/{workflow_item_id}/transition")
def transition(workflow_item_id: str, payload: WorkflowTransitionRequest,
               x_fortify_role: str | None = Header(default=None), x_fortify_purpose: str | None = Header(default=None)) -> dict[str, Any]:
    role, purpose = _security(x_fortify_role, x_fortify_purpose, f"/api/workflow/{workflow_item_id}/transition")
    try:
        return transition_item(workflow_item_id, new_state=payload.new_state, actor_role=role, purpose=purpose, reason_code=payload.reason_code)
    except PermissionError as exc: raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{workflow_item_id}/history")
def history(workflow_item_id: str, x_fortify_role: str | None = Header(default=None), x_fortify_purpose: str | None = Header(default=None)) -> dict[str, Any]:
    role, purpose = _security(x_fortify_role, x_fortify_purpose, f"/api/workflow/{workflow_item_id}/history")
    decision = authorize(role, purpose)
    if not decision.allowed: raise HTTPException(status_code=403, detail=decision.reason)
    item = get_item(workflow_item_id)
    if item is None: raise HTTPException(status_code=404, detail="Workflow item not found")
    if role not in {SecurityRole.WELFARE_OFFICER.value, SecurityRole.AUDITOR.value}:
        raise HTTPException(status_code=403, detail="Workflow history is restricted to authorized welfare or audit access.")
    return {"workflow_item_id": workflow_item_id, "events": get_history(workflow_item_id), "count": len(get_history(workflow_item_id))}
