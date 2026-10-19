from __future__ import annotations

import csv
from pathlib import Path
import json
import re
from datetime import datetime, timezone
from threading import RLock
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends as FastAPIDepends, HTTPException, Query

from app.api.dependencies import (
    require_aggregate,
    require_audit,
    require_infrastructure,
    require_unit_access,
    require_welfare,
    require_principal,
    unit_scope_for,
)
from app.core import database
from app.core.database import check_database
from app.core.paths import ARTIFACTS_DIR as _DEFAULT_ARTIFACTS_DIR
from app.core.paths import AUDIT_PATH as _DEFAULT_AUDIT_PATH
from app.core.paths import DATA_DIR as _DEFAULT_DATA_DIR
from app.security.audit import AuditLog
from app.security.principal import Principal
from app.services.workflow import (
    DataUnavailable,
    _workflow_id,
    get_item,
    open_case_id_for_person,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# Module-level so tests can patch these locations in isolation.
DATA_DIR = _DEFAULT_DATA_DIR
AUDIT_PATH = _DEFAULT_AUDIT_PATH
ARTIFACTS_DIR = _DEFAULT_ARTIFACTS_DIR

_SUMMARY_CACHE: dict[str, Any] = {}
_SUMMARY_SIGNATURE: tuple[int, int] | None = None
_SUMMARY_CACHE_LOCK = RLock()
_RECORD_COUNTS_CACHE: dict[str, tuple[tuple[int, ...], int]] = {}
_EXPLANATIONS_CACHE: dict[str, Any] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_csv(name: str, columns: list[str] | None = None) -> pd.DataFrame:
    path = DATA_DIR / name
    if not path.exists():
        raise HTTPException(
            status_code=503,
            detail=f"Required dashboard artifact is unavailable: {name}. Generate the demo dataset first (python scripts/build_all.py).",
        )
    try:
        return pd.read_csv(path, usecols=columns)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Unable to read dashboard artifact: {name}") from exc


def _audit_access(role: str, purpose: str, outcome: str, resource: str, details: dict[str, Any]) -> None:
    from app.security.audit import AuditEvent

    AuditLog(AUDIT_PATH).append(AuditEvent(
        event_type="DASHBOARD_ACCESS", actor_role=role, purpose=purpose, outcome=outcome,
        resource=resource, timestamp=_utc_now(), details=details))


# Audit path used by the shared authorization helpers. Module-level so tests can
# patch it in isolation alongside AUDIT_PATH.
def _authz_audit_path():
    return AUDIT_PATH


def _with_units(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach unit_id to a person-day frame; a left join, so no row is dropped."""
    if "unit_id" in frame.columns:
        return frame
    return frame.merge(
        _read_csv("personnel.csv", ["person_id", "unit_id"]),
        on="person_id", how="left", validate="many_to_one",
    )


def _scoped(frame: pd.DataFrame, principal: Principal) -> pd.DataFrame:
    """Restrict rows to the caller's units BEFORE any count, sort or page.

    Filtering after pagination would leak other units' people into the totals and
    let a scoped officer infer the size of the rest of the force. A caller whose
    scope cannot be resolved sees nothing - that is the fail-closed behaviour.
    """
    scope = unit_scope_for(principal)
    if scope.all_units:
        return frame
    if not scope.units:
        return frame.iloc[0:0]
    joined = _with_units(frame)
    return joined[joined["unit_id"].astype(str).isin(scope.units)]


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


def _load_explanations() -> dict[tuple[str, str], dict[str, Any]]:
    """Load structured explanations for flagged person-days, cached by mtime.

    Explanations are written by the Phase 5 pipeline for EARLY_WARNING rows
    only, so this file is far smaller than the decision CSVs. A missing file
    degrades to "no structured explanation" rather than an error: the summary
    sentence column remains available.
    """
    path = DATA_DIR / "explanations.jsonl"
    if not path.exists():
        return {}
    signature = _artifact_signature(path)
    cached = _EXPLANATIONS_CACHE.get("map")
    if cached is not None and _EXPLANATIONS_CACHE.get("signature") == signature:
        return cached
    mapping: dict[tuple[str, str], dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = (str(record.get("person_id")), str(record.get("date")))
        mapping[key] = record
    _EXPLANATIONS_CACHE["map"] = mapping
    _EXPLANATIONS_CACHE["signature"] = signature
    return mapping


def _artifact_signature(path: Path) -> int | None:
    """Mtime signature for cache invalidation; missing artifacts are None so a
    deployment without generated data degrades to the 503 path instead of a
    raw FileNotFoundError, and the cache still invalidates once data appears."""
    return path.stat().st_mtime_ns if path.exists() else None


def _dashboard_frame() -> pd.DataFrame:
    global _SUMMARY_SIGNATURE
    p6_path = DATA_DIR / "intervention_recommendations.csv"
    p7_path = DATA_DIR / "intervention_feasibility.csv"
    signature = (_artifact_signature(p6_path), _artifact_signature(p7_path))
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


def _record_count(name: str) -> int | None:
    """Count data rows (not header) of a CSV, honoring quoted newlines. Cached by mtime."""
    path = DATA_DIR / name
    if not path.exists():
        return None
    signature = (path.stat().st_mtime_ns,)
    cached = _RECORD_COUNTS_CACHE.get(name)
    if cached and cached[0] == signature:
        return cached[1]
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            count = sum(1 for _ in csv.reader(handle))
        count = max(0, count - 1)
    except OSError:
        return None
    _RECORD_COUNTS_CACHE[name] = (signature, count)
    return count


@router.get("/overview")
def overview(principal: Principal = FastAPIDepends(require_principal)) -> dict[str, Any]:
    """Aggregate operational overview.

    This endpoint returns band/priority/feasibility *counts* and never any
    personnel identifier, so both aggregate and welfare callers may read it -
    a welfare officer working a case list still needs the population context.

    The per-person case list lives behind ``/attention``, which requires
    welfare purpose.
    """
    if principal.purpose.value == "WELFARE_SUPPORT":
        require_welfare(principal, "/api/dashboard/overview", _authz_audit_path())
    else:
        require_aggregate(principal, "/api/dashboard/overview", _authz_audit_path())
    df = _scoped(_dashboard_frame(), principal)
    if df.empty:
        # A caller with no unit scope, or whose units have no records on this
        # artifact, gets an honest zero rather than NaN leaking into the JSON.
        return {"phase": "Phase 9 — Dashboard Integration", "as_of_date": None,
                "personnel_count": 0, "risk_band_counts": {}, "feasibility_counts": {},
                "priority_counts": {}, "high_band_count": 0, "requires_human_review_count": 0,
                "scope_note": "No personnel are visible to this caller's unit scope.",
                "data_policy": "Aggregate counts only; no personnel identifiers and no raw wellness responses are exposed."}
    latest_date = df["date"].max()
    latest = df[df["date"] == latest_date]
    band_counts = latest["risk_band"].value_counts().to_dict()
    feasibility_counts = latest["feasibility_status"].value_counts().to_dict()
    priority_counts = latest["priority"].value_counts().to_dict()
    return {"phase": "Phase 9 — Dashboard Integration", "as_of_date": latest_date,
            "personnel_count": int(df["person_id"].nunique()),
            "risk_band_counts": {str(k): int(v) for k, v in band_counts.items()},
            "feasibility_counts": {str(k): int(v) for k, v in feasibility_counts.items()},
            "priority_counts": {str(k): int(v) for k, v in priority_counts.items()},
            "high_band_count": int((latest["risk_band"].astype(str) == "HIGH").sum()),
            "requires_human_review_count": int(latest["requires_human_review_phase7"].fillna(False).astype(bool).sum()),
            "data_policy": "Aggregate counts only; no personnel identifiers and no raw wellness responses are exposed."}


@router.get("/attention")
def attention(limit: int = Query(default=25, ge=1, le=100),
              principal: Principal = FastAPIDepends(require_principal)) -> dict[str, Any]:
    """Per-person cases needing human review. Welfare purpose only."""
    require_welfare(principal, "/api/dashboard/attention", _authz_audit_path())
    df = _scoped(_dashboard_frame(), principal)
    if df.empty:
        return {"as_of_date": None, "cases": [], "count": 0,
                "privacy_note": "Individual welfare detail; requires welfare-support authorization."}
    latest_date = df["date"].max()
    latest = df[df["date"] == latest_date]
    recent_high = latest[latest["risk_band"].astype(str).eq("HIGH")].sort_values(
        ["welfare_risk_probability", "person_id"], ascending=[False, True]
    ).head(limit)
    cases = [
        {"person_id": str(r.person_id), "date": str(r.date),
         "risk_probability": float(r.welfare_risk_probability), "risk_band": str(r.risk_band),
         "recommended_action": str(r.recommended_action), "priority": str(r.priority),
         "feasibility_status": str(r.feasibility_status),
         "requires_human_review": bool(r.requires_human_review_phase7)}
        for r in recent_high.itertuples(index=False)
    ]
    return {"as_of_date": latest_date, "cases": cases, "count": len(cases),
            "privacy_note": "Individual welfare detail; requires welfare-support authorization."}


@router.get("/trend")
def trend(days: int = Query(default=30, ge=7, le=90),
          principal: Principal = FastAPIDepends(require_principal)) -> dict[str, Any]:
    require_aggregate(principal, "/api/dashboard/trend", _authz_audit_path())
    df = _scoped(_dashboard_frame(), principal)
    dates = sorted(df["date"].unique())[-days:]; recent = df[df["date"].isin(dates)]
    grouped = recent.groupby("date", sort=True).agg(
        average_probability=("welfare_risk_probability", "mean"),
        high_count=("risk_band", lambda s: int((s == "HIGH").sum())),
        constrained_count=("feasibility_status", lambda s: int(s.isin(["CONSTRAINED", "NOT_FEASIBLE"]).sum())),
        human_review_count=("requires_human_review_phase7", "sum"),
    ).reset_index()
    return {"days": len(grouped), "points": grouped.to_dict(orient="records")}


@router.get("/units")
def units(principal: Principal = FastAPIDepends(require_principal)) -> dict[str, Any]:
    require_aggregate(principal, "/api/dashboard/units", _authz_audit_path())
    df = _with_units(_scoped(_dashboard_frame(), principal))
    if df.empty:
        return {"as_of_date": None, "units": []}
    latest_date = df["date"].max()
    latest = df[df["date"] == latest_date]
    summary = latest.groupby("unit_id", dropna=False).agg(
        personnel=("person_id", "nunique"), high_risk=("risk_band", lambda s: int((s == "HIGH").sum())),
        constrained=("feasibility_status", lambda s: int(s.isin(["CONSTRAINED", "NOT_FEASIBLE"]).sum())), human_review=("requires_human_review_phase7", "sum"),
    ).reset_index().sort_values(["high_risk", "unit_id"], ascending=[False, True])
    return {"as_of_date": latest_date, "units": summary.to_dict(orient="records")}


@router.get("/unit/{unit_id}")
def unit_detail(unit_id: str, principal: Principal = FastAPIDepends(require_principal)) -> dict[str, Any]:
    require_aggregate(principal, f"/api/dashboard/unit/{unit_id}", _authz_audit_path())
    require_unit_access(principal, unit_id, f"/api/dashboard/unit/{unit_id}", "aggregate",
                        _authz_audit_path(), not_found_message="Unit not found")
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
def person_detail(person_id: str, principal: Principal = FastAPIDepends(require_principal)) -> dict[str, Any]:
    require_welfare(principal, f"/api/dashboard/person/{person_id}", _authz_audit_path())
    df = _dashboard_frame(); person = df[df["person_id"].astype(str) == person_id].sort_values("date")
    if person.empty: raise HTTPException(status_code=404, detail="Personnel record not found")
    history = person.tail(30)
    latest = history.iloc[-1]
    identity = _read_csv("personnel.csv", ["person_id", "unit_id", "role", "deployment_type"])
    identity_matches = identity[identity["person_id"].astype(str) == person_id]
    # A person can appear in the decision stream without a personnel row. That
    # is a data-integrity problem, not a crash: report it as not-found rather
    # than raising IndexError and returning 500.
    if identity_matches.empty:
        raise HTTPException(status_code=404, detail="Personnel record not found")
    identity_row = identity_matches.iloc[0]
    # Object-level check: welfare purpose alone is not enough, the person must be
    # in this caller's units. Denied answers repeat the not-found text verbatim so
    # the endpoint cannot be used to discover which personnel ids exist.
    require_unit_access(principal, str(identity_row["unit_id"]),
                        f"/api/dashboard/person/{person_id}", "welfare", _authz_audit_path(),
                        not_found_message="Personnel record not found")
    workflow_id = _workflow_id(person_id, str(latest["date"]))
    principal_scope = unit_scope_for(principal)
    try:
        workflow_item = get_item(workflow_id, unit_scope=principal_scope)
        if workflow_item is None:
            # The case was opened on an earlier day and is still awaiting a
            # decision; showing "no case" here would hide actionable work.
            open_id = open_case_id_for_person(person_id, principal_scope)
            workflow_item = get_item(open_id, unit_scope=principal_scope) if open_id else None
    except DataUnavailable:
        workflow_item = None
    workflow_payload = None
    if workflow_item:
        workflow_payload = dict(workflow_item)  # get_item already embeds history/support/feedback/followup
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
            "explanation": _load_explanations().get((person_id, str(latest["date"]))),
            "privacy_note": "Raw wellness/self-report responses are not exposed by the dashboard API."}


@router.get("/personnel")
def personnel(query: str = Query(default="", max_length=40), unit_id: str | None = Query(default=None, max_length=40), risk_band: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=100),
              principal: Principal = FastAPIDepends(require_principal)) -> dict[str, Any]:
    require_welfare(principal, "/api/dashboard/personnel", _authz_audit_path())
    df = _with_units(_scoped(_dashboard_frame(), principal))
    latest = df.sort_values("date").groupby("person_id", as_index=False).tail(1)
    if query: latest = latest[latest["person_id"].astype(str).str.contains(query, case=False, regex=False)]
    if unit_id: latest = latest[latest["unit_id"].astype(str) == unit_id]
    if risk_band: latest = latest[latest["risk_band"].astype(str) == risk_band]
    # Filter, then page, so `total` reflects the full filtered result set and the
    # client can tell "page 1 of N" from "these are all of them".
    total_matching = int(len(latest))
    latest = latest.sort_values(["risk_band", "welfare_risk_probability", "person_id"], ascending=[True, False, True]).head(limit)
    items = [{"person_id": str(r.person_id), "unit_id": str(r.unit_id), "date": str(r.date), "risk_band": str(r.risk_band), "risk_probability": float(r.welfare_risk_probability),
              "recommended_action": str(r.recommended_action), "priority": str(r.priority), "feasibility_status": str(r.feasibility_status)} for r in latest.itertuples(index=False)]
    return {"items": items, "count": len(items), "total_personnel": int(df["person_id"].nunique()),
            "total_matching": total_matching, "limit": limit,
            "truncated": total_matching > len(items),
            "privacy_note": "Individual operational welfare detail requires welfare-support authorization."}


@router.get("/search")
def search(query: str = Query(min_length=1, max_length=50), limit: int = Query(default=12, ge=1, le=30),
           principal: Principal = FastAPIDepends(require_principal)) -> dict[str, Any]:
    q = query.strip().lower(); results: list[dict[str, Any]] = []
    units_df = _read_csv("personnel.csv", ["person_id", "unit_id"]).drop_duplicates()
    # Scope the candidate set first: searching must not report how many people or
    # units exist outside the caller's own units.
    scope = unit_scope_for(principal)
    if not scope.all_units:
        if not scope.units:
            return {"query": query, "results": [], "privacy_note": "No personnel are visible to this caller's unit scope."}
        units_df = units_df[units_df["unit_id"].astype(str).isin(scope.units)]
    matching_units = sorted(set(units_df.loc[units_df["unit_id"].astype(str).str.lower().str.contains(q, regex=False), "unit_id"].astype(str)))
    # Aggregate purpose sees units only; welfare purpose additionally sees
    # individual personnel. This branch is the purpose check.
    if principal.purpose.value == "AGGREGATE_OPERATIONS":
        for unit in matching_units[:limit]: results.append({"type": "UNIT", "key": unit, "title": unit, "detail": "Aggregate operational context"})
        return {"query": query, "results": results, "privacy_note": "Aggregate search does not expose individual personnel records."}
    require_welfare(principal, "/api/dashboard/search", _authz_audit_path())
    for person in sorted(set(units_df.loc[units_df["person_id"].astype(str).str.lower().str.contains(q, regex=False), "person_id"].astype(str)))[:limit]:
        results.append({"type": "PERSONNEL", "key": person, "title": person, "detail": "Authorized welfare profile"})
    for unit in matching_units[:max(0, limit-len(results))]: results.append({"type": "UNIT", "key": unit, "title": unit, "detail": "Aggregate operational context"})
    return {"query": query, "results": results[:limit], "privacy_note": "Search results contain identifiers only; welfare detail requires the person profile view."}


@router.get("/data-sources")
def data_sources(principal: Principal = FastAPIDepends(require_principal)) -> dict[str, Any]:
    require_aggregate(principal, "/api/dashboard/data-sources", _authz_audit_path())
    specs = [("Duty records", "duty_events.csv", "Operational"), ("Recovery", "recovery_events.csv", "Operational"), ("Leave", "leave_events.csv", "Operational"),
             ("Deployment", "deployment_events.csv", "Operational"), ("Training", "training_events.csv", "Operational"), ("Incidents", "incident_events.csv", "Operational"),
             ("Personnel", "personnel.csv", "Restricted context"), ("Risk decisions", "risk_decisions.csv", "Derived"), ("Recommendations", "intervention_recommendations.csv", "Derived"),
             ("Feasibility", "intervention_feasibility.csv", "Derived")]
    sources = []
    for label, filename, classification in specs:
        path = DATA_DIR / filename
        if not path.exists():
            sources.append({"name": label, "status": "Unavailable", "records": 0, "classification": classification}); continue
        records = _record_count(filename)
        sources.append({"name": label, "status": "Healthy", "records": records if records is not None else 0,
                        "last_updated": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
                        "classification": classification})
    return {"environment": "Synthetic demonstration environment", "sources": sources, "privacy_note": "Source contents are not exposed by this endpoint."}


@router.get("/audit")
def audit_view(limit: int = Query(default=25, ge=1, le=100),
               principal: Principal = FastAPIDepends(require_principal)) -> dict[str, Any]:
    require_audit(principal, "/api/dashboard/audit", _authz_audit_path())
    log = AuditLog(AUDIT_PATH)
    scope = unit_scope_for(principal)
    person_units: dict[str, str] = {}
    case_units: dict[str, str] = {}
    if not scope.all_units and scope.units:
        identity_path = DATA_DIR / "personnel.csv"
        if identity_path.exists():
            identity = pd.read_csv(identity_path, usecols=["person_id", "unit_id"]).drop_duplicates()
            person_units = {str(r.person_id): str(r.unit_id) for r in identity.itertuples(index=False)}
        case_units = _workflow_case_units()
    # Filter before the limit: paging the tail first would let out-of-scope
    # events crowd out the caller's own older events. Malformed lines are
    # counted across the whole log, not just the requested page.
    visible: list[dict[str, Any]] = []
    malformed = 0
    if AUDIT_PATH.exists():
        for line in AUDIT_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                # A truncated final record (crash mid-append, full disk) must not
                # take down the audit view - that is exactly when an auditor
                # most needs to read it. Count it and surface it instead.
                malformed += 1
                continue
            if not isinstance(record, dict):
                malformed += 1
                continue
            if _audit_event_visible(record, scope, person_units, case_units):
                visible.append(record)
    events = [{"event_type": record.get("event_type"), "actor_role": record.get("actor_role"), "purpose": record.get("purpose"),
               "outcome": record.get("outcome"), "resource": _redact_text(record.get("resource")), "timestamp": record.get("timestamp"),
               "details": _redact_details(record.get("details", {}))}
              for record in visible[-limit:]]
    verification = log.verify()
    return {"chain_valid": verification.valid, "chain_reason": verification.reason,
            "audit_records": verification.records, "audit_anchored": verification.anchored,
            "malformed_records": malformed,
            "event_count": len(events), "events": events,
            "privacy_note": "Audit output contains governance metadata only; raw wellness responses and direct personnel identifiers are excluded. Events are restricted to the caller's unit scope; chain verification is global."}


# Detail keys that carry a direct personnel identifier. The audit log keeps the
# full value on disk (it is the evidentiary record); the read API redacts it so
# the governance screen does not become a de facto personnel export.
_REDACTED_DETAIL_KEYS = {"person_id"}
_PERSON_ID_PATTERN = re.compile(r"P-[0-9]{3,}")
_UNIT_RESOURCE_PATTERN = re.compile(r"^/api/dashboard/unit/([^/?#]+)")
_CASE_RESOURCE_PATTERN = re.compile(r"^/api/workflow/([^/?#]+)")


def _workflow_case_units() -> dict[str, str]:
    """Map case id to unit so the audit view can filter case-scoped events.

    An unavailable store yields an empty map; callers treat an unresolvable
    case reference as out of scope rather than exposing it.
    """
    try:
        with database.connect() as conn:
            rows = conn.execute(
                "SELECT workflow_item_id, unit_id FROM workflow_items"
            ).fetchall()
    except Exception:  # noqa: BLE001 - audit reads must degrade, not fail the request
        return {}
    return {
        str(row[0]): str(row[1])
        for row in rows
        if row[1] is not None and str(row[1]).strip()
    }


def _detail_person_ids(value: Any) -> set[str]:
    """Collect every personnel identifier nested in an audit detail payload."""
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "person_id" and item is not None:
                found.add(str(item))
            else:
                found |= _detail_person_ids(item)
    elif isinstance(value, list):
        for item in value:
            found |= _detail_person_ids(item)
    return found


def _audit_event_visible(record: dict[str, Any], scope: Any, person_units: dict[str, str],
                         case_units: dict[str, str]) -> bool:
    """Whether an auditor scoped to ``scope`` may see this governance event.

    Events that name a unit, case or person must resolve inside the scope; an
    unresolvable reference is hidden (fail closed). Events with no subject
    reference are system-level governance metadata and remain visible.
    """
    if scope.all_units:
        return True
    if not scope.units:
        return False
    details = record.get("details")
    if details is None:
        details = {}
    details_named = False
    if isinstance(details, dict):
        unit_value = details.get("unit")
        if unit_value not in (None, ""):
            details_named = True
            requested = [part.strip() for part in str(unit_value).split(",") if part.strip()]
            if not requested or any(not scope.allows(unit) for unit in requested):
                return False
    person_ids = _detail_person_ids(details)
    resource = record.get("resource")
    if isinstance(resource, str):
        person_ids |= set(_PERSON_ID_PATTERN.findall(resource))
        unit_match = _UNIT_RESOURCE_PATTERN.match(resource)
        if unit_match and not scope.allows(unit_match.group(1)):
            return False
        case_match = _CASE_RESOURCE_PATTERN.match(resource)
        if case_match:
            case_unit = case_units.get(case_match.group(1))
            if case_unit is not None:
                if not scope.allows(case_unit):
                    return False
            elif not person_ids and not details_named:
                # The resource names a case but its unit cannot be resolved and
                # no other subject detail establishes scope: fail closed.
                return False
    for person_id in person_ids:
        unit_id = person_units.get(person_id)
        if unit_id is None or not scope.allows(unit_id):
            return False
    return True


def _redact_text(value: Any) -> Any:
    """Redact personnel identifiers from free-text fields (URL paths in
    resource fields, string details). The on-disk log keeps full values; the
    read API does not."""
    if not isinstance(value, str):
        return value
    return _PERSON_ID_PATTERN.sub("[redacted:personnel-identifier]", value)


def _redact_details(details: Any) -> Any:
    if not isinstance(details, dict):
        return _redact_text(details)
    return {
        key: ("[redacted:personnel-identifier]" if key in _REDACTED_DETAIL_KEYS else _redact_details(value) if isinstance(value, dict) else _redact_text(value))
        for key, value in details.items()
    }


_REVIEW_QUEUE_CACHE: dict[str, Any] = {}
_REVIEW_QUEUE_LOCK = RLock()


def _load_review_queue() -> pd.DataFrame:
    """Load and cache the review queue by mtime, like the other artifacts.

    This endpoint serves welfare officers on every screen load; re-parsing the
    CSV per request measured ~1.2s at p95 under load, the single worst warm
    path in the API.
    """
    path = DATA_DIR / "review_queue.csv"
    if not path.exists():
        raise HTTPException(status_code=503, detail="Review queue is unavailable; generate the dataset (python scripts/build_all.py).")
    signature = _artifact_signature(path)
    with _REVIEW_QUEUE_LOCK:
        cached = _REVIEW_QUEUE_CACHE.get("frame")
        if cached is not None and _REVIEW_QUEUE_CACHE.get("signature") == signature:
            return cached
        queue = pd.read_csv(path, usecols=["person_id", "date", "score", "risk_band",
                                           "alert_state", "case_created", "suppressed_by_budget",
                                           "evidence_days", "reason"])
        queue["date"] = queue["date"].astype(str)
        _REVIEW_QUEUE_CACHE["frame"] = queue
        _REVIEW_QUEUE_CACHE["signature"] = signature
        return queue


@router.get("/review-queue")
def review_queue(date: str | None = Query(default=None, max_length=10),
                 principal: Principal = FastAPIDepends(require_principal)) -> dict[str, Any]:
    """The alert-policy review queue: which scores became human work today.

    This is the operational answer to "what should I review next?" - cases the
    deterministic alert policy promoted, plus the candidates suppressed by the
    daily budget so the selection is auditable rather than silent.
    """
    require_welfare(principal, "/api/dashboard/review-queue", _authz_audit_path())
    queue = _load_review_queue()
    scope = unit_scope_for(principal)
    if not scope.all_units:
        if not scope.units:
            return {"date": None, "cases": [], "suppressed_by_budget": [], "case_count": 0,
                    "suppressed_count": 0, "open_signal_count": 0,
                    "privacy_note": "No personnel are visible to this caller's unit scope."}
        identities = _read_csv("personnel.csv", ["person_id", "unit_id"])
        visible = set(identities.loc[identities["unit_id"].astype(str).isin(scope.units), "person_id"].astype(str))
        queue = queue[queue["person_id"].astype(str).isin(visible)]
    if queue.empty:
        return {"date": None, "cases": [], "suppressed_by_budget": [], "case_count": 0,
                "suppressed_count": 0, "open_signal_count": 0,
                "privacy_note": "Queue metadata only; open individual cases through the welfare views."}
    target = date or str(queue["date"].max())
    day = queue[queue["date"] == target]
    cases = day[day["case_created"].astype(str).str.lower().isin(("true", "1"))]
    suppressed = day[day["suppressed_by_budget"].astype(str).str.lower().isin(("true", "1"))]
    # Days where every candidate is already inside an open case are a
    # legitimate and common answer: "no new cases today, N open signals".
    open_signals = day[day["alert_state"].isin(["PERSISTENT", "ESCALATED"])]
    return {
        "date": target,
        "cases": cases.sort_values(["score", "person_id"], ascending=[False, True]).to_dict(orient="records"),
        "suppressed_by_budget": suppressed.to_dict(orient="records"),
        "case_count": int(len(cases)),
        "suppressed_count": int(len(suppressed)),
        "open_signal_count": int(len(open_signals)),
        "privacy_note": "Queue metadata only; open individual cases through the welfare views.",
    }


_DRIFT_CACHE: dict[str, Any] = {}
_DRIFT_LOCK = RLock()


def _freshness_and_drift() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    path = DATA_DIR / "risk_decisions.csv"
    if not path.exists():
        return None, None
    signature = _artifact_signature(path)
    with _DRIFT_LOCK:
        cached = _DRIFT_CACHE.get("value")
        if cached is not None and _DRIFT_CACHE.get("signature") == signature:
            return cached
    decisions = _read_csv("risk_decisions.csv", ["person_id", "date", "welfare_risk_probability"])
    decisions["date"] = pd.to_datetime(decisions["date"])
    latest_day = decisions["date"].max()
    freshness = {"latest_event_date": str(latest_day.date()),
                 "age_days": int((pd.Timestamp.now() - latest_day).days)}
    drift = None
    decisions["period"] = decisions["date"].dt.to_period("M").astype(str)
    monthly = decisions.groupby("period")["welfare_risk_probability"].mean()
    if len(monthly) >= 3:
        recent, prior = monthly.iloc[-1], monthly.iloc[:-1].mean()
        drift = {"recent_mean_score": round(float(recent), 4),
                 "prior_mean_score": round(float(prior), 4),
                 "shift": round(float(recent - prior), 4),
                 "note": "Review indicator only; the score distribution drifting does not change the deployed model automatically."}
    with _DRIFT_LOCK:
        _DRIFT_CACHE["value"] = (freshness, drift)
        _DRIFT_CACHE["signature"] = signature
    return freshness, drift


@router.get("/system-health")
def system_health(principal: Principal = FastAPIDepends(require_principal)) -> dict[str, Any]:
    # Health is intentionally readable by BOTH the infrastructure administrator
    # and the auditor: verifying the audit chain's health is part of an
    # auditor's job. It exposes no personnel data.
    if principal.purpose.value == "INFRASTRUCTURE_ADMIN":
        require_infrastructure(principal, "/api/dashboard/system-health", _authz_audit_path())
    elif principal.purpose.value == "AUDIT":
        require_audit(principal, "/api/dashboard/system-health", _authz_audit_path())
    else:
        raise HTTPException(status_code=403, detail="System health is restricted to administrative or audit roles.")
    db_ok = check_database()
    verification = AuditLog(AUDIT_PATH).verify_incremental()
    # Only artifacts the running API actually consumes at request time.
    artifacts = ["personnel.csv", "intervention_recommendations.csv", "intervention_feasibility.csv", "review_queue.csv"]
    artifact_status = {name: (DATA_DIR / name).exists() for name in artifacts}
    with _SUMMARY_CACHE_LOCK: cache_ready = "joined" in _SUMMARY_CACHE

    # Model and pipeline identity, so a deployment can be audited for running
    # the artifacts it thinks it is running.
    model_version = pipeline_version = None
    card_path = ARTIFACTS_DIR / "phase5" / "model_card.json"
    try:
        card = json.loads(card_path.read_text(encoding="utf-8"))
        model_version = card.get("model_identity", {}).get("phase5_model_version")
        pipeline_version = card.get("pipeline", {}).get("pipeline_version")
    except (OSError, json.JSONDecodeError):
        pass

    # Data freshness and a coarse score-drift indicator for review (never an
    # automatic retraining trigger). Cached by mtime: this endpoint is polled
    # by monitors, and the drift read parses an 18 MB CSV.
    freshness, drift = _freshness_and_drift()

    return {"application": {"api": "Healthy", "database": "Healthy" if db_ok else "Warning",
                            "dashboard_cache": "Warm" if cache_ready else "Cold"},
            "model": {"model_version": model_version, "pipeline_version": pipeline_version,
                      "alert_policy_version": "alert-policy-v1"},
            "data": {"artifacts": artifact_status, "freshness": freshness, "score_drift": drift},
            "governance": {"access_control": "Prototype role/purpose headers (not authenticated)",
                           "auth_method": principal.auth_method,
                           "authenticated": principal.authenticated,
                           "audit_chain": "Healthy" if verification.valid else "Failed",
                           "audit_chain_reason": verification.reason,
                           "audit_records": verification.records,
                           "audit_anchored": verification.anchored,
                           "security_boundary": "Prototype"},
            "synthetic_demo": True}
