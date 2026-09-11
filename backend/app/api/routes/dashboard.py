from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any

import pandas as pd
from fastapi import APIRouter, Header, HTTPException, Query

from app.core.config import settings
from app.security.audit import AuditEvent, AuditLog
from app.security.rbac import authorize
from app.security.security_config import AccessPurpose, SecurityRole
from app.services.workflow import get_history, get_item, _workflow_id

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = Path(os.getenv("FORTIFY_DATA_DIR", ROOT / "data" / "generated"))
AUDIT_PATH = Path(os.getenv("FORTIFY_AUDIT_LOG", ROOT / "artifacts" / "phase8" / "dashboard_audit.jsonl"))

_SUMMARY_CACHE: dict[str, Any] = {}
_SUMMARY_SIGNATURE: tuple[int, int] | None = None
_SUMMARY_CACHE_LOCK = RLock()


def _read_csv(name: str, columns: list[str] | None = None) -> pd.DataFrame:
    path = DATA_DIR / name
    if not path.exists():
        raise HTTPException(status_code=503, detail=f"Required dashboard artifact is unavailable: {name}")
    try:
        return pd.read_csv(path, usecols=columns)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Unable to read dashboard artifact: {name}") from exc


def _authorize(role: str, purpose: str, resource: str) -> None:
    decision = authorize(role, purpose)
    AuditLog(AUDIT_PATH).append(
        AuditEvent(
            event_type="DASHBOARD_ACCESS",
            actor_role=role,
            purpose=purpose,
            outcome="ALLOWED" if decision.allowed else "DENIED",
            resource=resource,
            timestamp=pd.Timestamp.utcnow().isoformat(),
            details={"policy_version": decision.policy_version},
        )
    )
    if not decision.allowed:
        raise HTTPException(status_code=403, detail=decision.reason)


def _require_headers(x_fortify_role: str | None, x_fortify_purpose: str | None) -> tuple[str, str]:
    role = x_fortify_role or ""
    purpose = x_fortify_purpose or ""
    if not role or not purpose:
        raise HTTPException(status_code=401, detail="Dashboard requires role and purpose headers in the prototype.")
    return role, purpose


def _require_welfare(role: str, purpose: str) -> None:
    if role != SecurityRole.WELFARE_OFFICER.value or purpose != AccessPurpose.WELFARE_SUPPORT.value:
        raise HTTPException(status_code=403, detail="Individual welfare access requires welfare-support authorization.")


def _require_aggregate(role: str, purpose: str) -> None:
    if purpose != AccessPurpose.AGGREGATE_OPERATIONS.value:
        raise HTTPException(status_code=403, detail="This view requires aggregate-operations purpose.")
    if role not in {SecurityRole.WELFARE_OFFICER.value, SecurityRole.COMMANDER.value}:
        raise HTTPException(status_code=403, detail="This view is restricted to authorized operational roles.")


def _load_phase5() -> pd.DataFrame:
    return _read_csv(
        "intervention_recommendations.csv",
        ["person_id", "date", "welfare_risk_probability", "risk_band", "threshold_decision", "contributing_signals", "model_version"],
    ).rename(columns={"contributing_signals": "contributing_operational_signals"})


def _load_phase6() -> pd.DataFrame:
    return _read_csv(
        "intervention_recommendations.csv",
        ["person_id", "date", "recommended_action", "priority", "requires_human_review", "policy_version"],
    )


def _load_phase7() -> pd.DataFrame:
    return _read_csv(
        "intervention_feasibility.csv",
        ["person_id", "date", "feasibility_status", "constraint_flags", "adjustment_recommendation", "requires_human_review", "feasibility_policy_version"],
    )


def _dashboard_frame() -> pd.DataFrame:
    global _SUMMARY_SIGNATURE
    p6_path = DATA_DIR / "intervention_recommendations.csv"
    p7_path = DATA_DIR / "intervention_feasibility.csv"
    signature = (p6_path.stat().st_mtime_ns, p7_path.stat().st_mtime_ns)
    with _SUMMARY_CACHE_LOCK:
        cached = _SUMMARY_CACHE.get("joined")
        if cached is not None and _SUMMARY_SIGNATURE == signature:
            return cached.copy()
        p5, p6, p7 = _load_phase5(), _load_phase6(), _load_phase7()
        for df in (p5, p6, p7):
            df["date"] = pd.to_datetime(df["date"], errors="raise").dt.strftime("%Y-%m-%d")
        joined = p5.merge(p6, on=["person_id", "date"], how="inner", validate="one_to_one").merge(
            p7, on=["person_id", "date"], how="inner", validate="one_to_one", suffixes=("_phase6", "_phase7")
        )
        _SUMMARY_CACHE["joined"] = joined.copy()
        _SUMMARY_SIGNATURE = signature
        return joined


@router.get("/overview")
def overview(x_fortify_role: str | None = Header(default=None), x_fortify_purpose: str | None = Header(default=None)) -> dict[str, Any]:
    role, purpose = _require_headers(x_fortify_role, x_fortify_purpose)
    _authorize(role, purpose, "/api/dashboard/overview")
    df = _dashboard_frame()
    latest_date = df["date"].max()
    latest = df[df["date"] == latest_date]
    band_counts = latest["risk_band"].value_counts().to_dict()
    feasibility_counts = latest["feasibility_status"].value_counts().to_dict()
    priority_counts = latest["priority"].value_counts().to_dict()
    recent_high = latest[latest["risk_band"].astype(str).eq("HIGH")].sort_values(["welfare_risk_probability", "person_id"], ascending=[False, True]).head(12)
    cases = [
        {"person_id": str(r.person_id), "date": str(r.date), "risk_probability": float(r.welfare_risk_probability), "risk_band": str(r.risk_band),
         "recommended_action": str(r.recommended_action), "priority": str(r.priority), "feasibility_status": str(r.feasibility_status),
         "requires_human_review": bool(r.requires_human_review_phase7)}
        for r in recent_high.itertuples(index=False)
    ]
    return {"phase": "Phase 9 — Dashboard Integration", "as_of_date": latest_date, "personnel_count": int(df["person_id"].nunique()),
            "risk_band_counts": {str(k): int(v) for k, v in band_counts.items()},
            "feasibility_counts": {str(k): int(v) for k, v in feasibility_counts.items()},
            "priority_counts": {str(k): int(v) for k, v in priority_counts.items()}, "high_priority_cases": cases,
            "data_policy": "Operational summaries only; raw wellness responses are not exposed."}


@router.get("/trend")
def trend(days: int = Query(default=30, ge=7, le=90), x_fortify_role: str | None = Header(default=None), x_fortify_purpose: str | None = Header(default=None)) -> dict[str, Any]:
    role, purpose = _require_headers(x_fortify_role, x_fortify_purpose)
    _authorize(role, purpose, "/api/dashboard/trend")
    df = _dashboard_frame(); dates = sorted(df["date"].unique())[-days:]; recent = df[df["date"].isin(dates)]
    grouped = recent.groupby("date", sort=True).agg(
        average_probability=("welfare_risk_probability", "mean"),
        high_count=("risk_band", lambda s: int((s == "HIGH").sum())),
        constrained_count=("feasibility_status", lambda s: int(s.isin(["CONSTRAINED", "NOT_FEASIBLE"]).sum())),
        human_review_count=("requires_human_review_phase7", "sum"),
    ).reset_index()
    return {"days": len(grouped), "points": grouped.to_dict(orient="records")}


@router.get("/units")
def units(x_fortify_role: str | None = Header(default=None), x_fortify_purpose: str | None = Header(default=None)) -> dict[str, Any]:
    role, purpose = _require_headers(x_fortify_role, x_fortify_purpose)
    _authorize(role, purpose, "/api/dashboard/units")
    df = _dashboard_frame(); personnel = _read_csv("personnel.csv", ["person_id", "unit_id"]); latest_date = df["date"].max()
    latest = df[df["date"] == latest_date].merge(personnel, on="person_id", how="left", validate="many_to_one")
    summary = latest.groupby("unit_id", dropna=False).agg(
        personnel=("person_id", "nunique"), high_risk=("risk_band", lambda s: int((s == "HIGH").sum())),
        constrained=("feasibility_status", lambda s: int(s.isin(["CONSTRAINED", "NOT_FEASIBLE"]).sum())), human_review=("requires_human_review_phase7", "sum"),
    ).reset_index().sort_values(["high_risk", "unit_id"], ascending=[False, True])
    return {"as_of_date": latest_date, "units": summary.to_dict(orient="records")}


@router.get("/unit/{unit_id}")
def unit_detail(unit_id: str, x_fortify_role: str | None = Header(default=None), x_fortify_purpose: str | None = Header(default=None)) -> dict[str, Any]:
    role, purpose = _require_headers(x_fortify_role, x_fortify_purpose)
    _authorize(role, purpose, f"/api/dashboard/unit/{unit_id}")
    _require_aggregate(role, purpose)
    df = _dashboard_frame().merge(_read_csv("personnel.csv", ["person_id", "unit_id"]), on="person_id", how="left", validate="many_to_one")
    scoped = df[df["unit_id"].astype(str) == unit_id]
    if scoped.empty:
        raise HTTPException(status_code=404, detail="Unit not found")
    recent = scoped.sort_values("date").groupby("date", sort=True).agg(
        average_probability=("welfare_risk_probability", "mean"), high_count=("risk_band", lambda s: int((s == "HIGH").sum())),
        constrained_count=("feasibility_status", lambda s: int(s.isin(["CONSTRAINED", "NOT_FEASIBLE"]).sum())),
    ).reset_index().tail(30)
    latest = scoped[scoped["date"] == scoped["date"].max()]
    return {"unit_id": unit_id, "personnel": int(latest["person_id"].nunique()), "as_of_date": str(latest["date"].max()),
            "high_count": int((latest["risk_band"] == "HIGH").sum()),
            "constrained_count": int(latest["feasibility_status"].isin(["CONSTRAINED", "NOT_FEASIBLE"]).sum()),
            "trend": recent.to_dict(orient="records"),
            "privacy_note": "Aggregate unit context only; individual personnel identifiers are not exposed in command view."}


@router.get("/person/{person_id}")
def person_detail(person_id: str, x_fortify_role: str | None = Header(default=None), x_fortify_purpose: str | None = Header(default=None)) -> dict[str, Any]:
    role, purpose = _require_headers(x_fortify_role, x_fortify_purpose)
    _authorize(role, purpose, f"/api/dashboard/person/{person_id}")
    _require_welfare(role, purpose)
    df = _dashboard_frame(); person = df[df["person_id"].astype(str) == person_id].sort_values("date")
    if person.empty: raise HTTPException(status_code=404, detail="Personnel record not found")
    history = person.tail(30)
    latest = history.iloc[-1]
    personnel_path = DATA_DIR / "personnel.csv"
    identity = _read_csv("personnel.csv", ["person_id", "unit_id", "role", "deployment_type"])
    identity_row = identity[identity["person_id"].astype(str) == person_id].iloc[0]
    workflow_id = _workflow_id(person_id, str(latest["date"]))
    workflow_item = get_item(workflow_id)
    workflow_history = get_history(workflow_id) if workflow_item else []
    workflow_payload = None
    if workflow_item:
        workflow_payload = dict(workflow_item)
        workflow_payload["history"] = workflow_history
    return {"person_id": person_id, "unit_id": str(identity_row["unit_id"]), "role": str(identity_row["role"]), "deployment_type": str(identity_row["deployment_type"]),
            "date_range": [str(history["date"].min()), str(history["date"].max())],
            "latest": {"date": str(latest["date"]), "risk_probability": float(latest["welfare_risk_probability"]), "risk_band": str(latest["risk_band"]),
                       "threshold_decision": str(latest["threshold_decision"]), "recommended_action": str(latest["recommended_action"]),
                       "priority": str(latest["priority"]), "feasibility_status": str(latest["feasibility_status"]), "constraint_flags": str(latest["constraint_flags"] or ""),
                       "requires_human_review": bool(latest["requires_human_review_phase7"]),
                       "contributing_operational_signals": str(latest.get("contributing_operational_signals", "") or ""),
                       "adjustment_recommendation": str(latest.get("adjustment_recommendation", "") or "")},
            "history": [{"date": str(r.date), "risk_probability": float(r.welfare_risk_probability), "risk_band": str(r.risk_band), "feasibility_status": str(r.feasibility_status)} for r in history.itertuples(index=False)],
            "workflow": workflow_payload,
            "privacy_note": "Raw wellness/self-report responses are not exposed by the dashboard API."}


@router.get("/personnel")
def personnel(query: str = Query(default="", max_length=40), unit_id: str | None = Query(default=None, max_length=40), risk_band: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=100),
              x_fortify_role: str | None = Header(default=None), x_fortify_purpose: str | None = Header(default=None)) -> dict[str, Any]:
    role, purpose = _require_headers(x_fortify_role, x_fortify_purpose); _authorize(role, purpose, "/api/dashboard/personnel"); _require_welfare(role, purpose)
    df = _dashboard_frame().merge(_read_csv("personnel.csv", ["person_id", "unit_id"]), on="person_id", how="left", validate="many_to_one")
    latest = df.sort_values("date").groupby("person_id", as_index=False).tail(1)
    if query: latest = latest[latest["person_id"].astype(str).str.contains(query, case=False, regex=False)]
    if unit_id: latest = latest[latest["unit_id"].astype(str) == unit_id]
    if risk_band: latest = latest[latest["risk_band"].astype(str) == risk_band]
    latest = latest.sort_values(["risk_band", "welfare_risk_probability", "person_id"], ascending=[True, False, True]).head(limit)
    items = [{"person_id": str(r.person_id), "unit_id": str(r.unit_id), "date": str(r.date), "risk_band": str(r.risk_band), "risk_probability": float(r.welfare_risk_probability),
              "recommended_action": str(r.recommended_action), "priority": str(r.priority), "feasibility_status": str(r.feasibility_status)} for r in latest.itertuples(index=False)]
    return {"items": items, "count": len(items), "total_personnel": int(df["person_id"].nunique()), "privacy_note": "Individual operational welfare detail requires welfare-support authorization."}


@router.get("/search")
def search(query: str = Query(min_length=1, max_length=50), limit: int = Query(default=12, ge=1, le=30), x_fortify_role: str | None = Header(default=None), x_fortify_purpose: str | None = Header(default=None)) -> dict[str, Any]:
    role, purpose = _require_headers(x_fortify_role, x_fortify_purpose); _authorize(role, purpose, "/api/dashboard/search")
    q = query.strip().lower(); results: list[dict[str, Any]] = []
    units_df = _read_csv("personnel.csv", ["person_id", "unit_id"]).drop_duplicates()
    matching_units = sorted(set(units_df.loc[units_df["unit_id"].astype(str).str.lower().str.contains(q, regex=False), "unit_id"].astype(str)))
    if purpose == AccessPurpose.AGGREGATE_OPERATIONS.value:
        for unit in matching_units[:limit]: results.append({"type": "UNIT", "key": unit, "title": unit, "detail": "Aggregate operational context"})
        return {"query": query, "results": results, "privacy_note": "Aggregate search does not expose individual personnel records."}
    _require_welfare(role, purpose)
    for person in sorted(set(units_df.loc[units_df["person_id"].astype(str).str.lower().str.contains(q, regex=False), "person_id"].astype(str)))[:limit]:
        results.append({"type": "PERSONNEL", "key": person, "title": person, "detail": "Authorized welfare profile"})
    for unit in matching_units[:max(0, limit-len(results))]: results.append({"type": "UNIT", "key": unit, "title": unit, "detail": "Aggregate operational context"})
    return {"query": query, "results": results[:limit]}


@router.get("/data-sources")
def data_sources(x_fortify_role: str | None = Header(default=None), x_fortify_purpose: str | None = Header(default=None)) -> dict[str, Any]:
    role, purpose = _require_headers(x_fortify_role, x_fortify_purpose); _authorize(role, purpose, "/api/dashboard/data-sources"); _require_aggregate(role, purpose)
    specs = [("Duty records", "duty_events.csv", "Operational"), ("Recovery", "recovery_events.csv", "Operational"), ("Leave", "leave_events.csv", "Operational"),
             ("Deployment", "deployment_events.csv", "Operational"), ("Training", "training_events.csv", "Operational"), ("Incidents", "incident_events.csv", "Operational"),
             ("Personnel", "personnel.csv", "Restricted context"), ("Risk decisions", "risk_decisions.csv", "Derived"), ("Recommendations", "intervention_recommendations.csv", "Derived"),
             ("Feasibility", "intervention_feasibility.csv", "Derived")]
    sources=[]
    for label, filename, classification in specs:
        path=DATA_DIR/filename
        if not path.exists(): sources.append({"name":label,"status":"Unavailable","records":0,"classification":classification}); continue
        try: records=max(0,sum(1 for _ in path.open("r", encoding="utf-8"))-1)
        except OSError: records=0
        sources.append({"name":label,"status":"Healthy","records":records,"last_updated":pd.Timestamp(path.stat().st_mtime, unit="s", tz="UTC").isoformat(),"classification":classification})
    return {"environment":"Synthetic demonstration environment", "sources":sources, "privacy_note":"Source contents are not exposed by this endpoint."}


@router.get("/audit")
def audit_view(limit: int = Query(default=25, ge=1, le=100), x_fortify_role: str | None = Header(default=None), x_fortify_purpose: str | None = Header(default=None)) -> dict[str, Any]:
    role, purpose = _require_headers(x_fortify_role, x_fortify_purpose); _authorize(role, purpose, "/api/dashboard/audit")
    if role != SecurityRole.AUDITOR.value or purpose != AccessPurpose.AUDIT.value:
        raise HTTPException(status_code=403, detail="Audit view requires auditor authorization.")
    log=AuditLog(AUDIT_PATH); events=[]
    if AUDIT_PATH.exists():
        for line in AUDIT_PATH.read_text(encoding="utf-8").splitlines()[-limit:]:
            if line.strip():
                record=json.loads(line); details=record.get("details", {})
                events.append({"event_type":record.get("event_type"),"actor_role":record.get("actor_role"),"purpose":record.get("purpose"),"outcome":record.get("outcome"),"resource":record.get("resource"),"timestamp":record.get("timestamp"),"details":details})
    return {"chain_valid": log.verify_chain(), "event_count": len(events), "events": events, "privacy_note":"Audit output contains governance metadata only; raw wellness responses are excluded."}


@router.get("/system-health")
def system_health(x_fortify_role: str | None = Header(default=None), x_fortify_purpose: str | None = Header(default=None)) -> dict[str, Any]:
    role, purpose = _require_headers(x_fortify_role, x_fortify_purpose); _authorize(role, purpose, "/api/dashboard/system-health")
    if role not in {SecurityRole.SYSTEM_ADMINISTRATOR.value, SecurityRole.AUDITOR.value}:
        raise HTTPException(status_code=403, detail="System health is restricted to administrative or audit roles.")
    db_path = Path(settings.database_url.removeprefix("sqlite:///")) if settings.database_url.startswith("sqlite:///") else None
    audit_valid=AuditLog(AUDIT_PATH).verify_chain()
    artifacts=["personnel.csv","intervention_recommendations.csv","intervention_feasibility.csv","risk_predictions.csv"]
    artifact_status={name:(DATA_DIR/name).exists() for name in artifacts}
    db_ok=bool(db_path and db_path.exists())
    with _SUMMARY_CACHE_LOCK: cache_ready="joined" in _SUMMARY_CACHE
    return {"application":{"api":"Healthy","database":"Healthy" if db_ok else "Warning","cache":"Healthy" if cache_ready else "Cold"},
            "data":{"artifacts":artifact_status}, "governance":{"access_control":"Active","audit_chain":"Healthy" if audit_valid else "Failed","security_boundary":"Prototype"},
            "synthetic_demo":True}
