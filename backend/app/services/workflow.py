from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

import pandas as pd

from app.core.config import settings
from app.security.audit import AuditEvent, AuditLog
from app.security.rbac import authorize
from app.security.security_config import AccessPurpose, SecurityRole

WORKFLOW_STATES = {
    "NEW", "ACKNOWLEDGED", "IN_REVIEW", "SUPPORT_PLANNED", "SUPPORT_COMPLETED",
    "FOLLOW_UP_SCHEDULED", "FOLLOW_UP_DUE", "FOLLOW_UP_COMPLETED", "CLOSED",
    "COMPLETED", "DEFERRED", "DISMISSED",
}
ALLOWED_ACTIONS = {
    "WELLNESS_CHECK_IN", "RECOVERY_SUPPORT", "SUPERVISOR_WELFARE_REVIEW",
    "PRIORITY_WELFARE_REVIEW", "HUMAN_ESCALATION_RECOMMENDED", "ROUTINE_MONITORING",
    "CONTINUE_EXISTING_SUPPORT",
}
# COMPLETED is retained as a Phase 10 compatibility state meaning support completed.
TRANSITIONS = {
    "NEW": {"ACKNOWLEDGED", "DISMISSED"},
    "ACKNOWLEDGED": {"IN_REVIEW", "DEFERRED", "DISMISSED"},
    "IN_REVIEW": {"SUPPORT_PLANNED", "DEFERRED", "DISMISSED"},
    "SUPPORT_PLANNED": {"SUPPORT_COMPLETED", "COMPLETED", "DEFERRED"},
    "SUPPORT_COMPLETED": {"FOLLOW_UP_SCHEDULED", "CLOSED", "SUPPORT_PLANNED"},
    "COMPLETED": set(),
    "FOLLOW_UP_SCHEDULED": {"FOLLOW_UP_DUE", "FOLLOW_UP_COMPLETED", "DEFERRED"},
    "FOLLOW_UP_DUE": {"FOLLOW_UP_COMPLETED", "SUPPORT_PLANNED", "DEFERRED"},
    "FOLLOW_UP_COMPLETED": {"CLOSED", "SUPPORT_PLANNED"},
    "CLOSED": set(),
    "DEFERRED": {"ACKNOWLEDGED", "IN_REVIEW", "DISMISSED"},
    "DISMISSED": set(),
}

@dataclass(frozen=True)
class WorkflowPolicyConfig:
    workflow_policy_version: str = "phase10-v1"
    review_role: str = SecurityRole.WELFARE_OFFICER.value
    review_purpose: str = AccessPurpose.WELFARE_SUPPORT.value

_DECISION_CACHE: tuple[tuple[int, int, int], pd.DataFrame] | None = None
_DECISION_CACHE_LOCK = RLock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=10.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def _data_signature(data_dir: Path) -> tuple[int, int, int]:
    names = ("intervention_recommendations.csv", "intervention_feasibility.csv")
    mtimes = []
    for name in names:
        path = data_dir / name
        if not path.exists():
            raise FileNotFoundError(path)
        mtimes.append(path.stat().st_mtime_ns)
    return (mtimes[0], mtimes[1], int(data_dir.stat().st_mtime_ns))


def _db_path() -> Path:
    prefix = "sqlite:///"
    if not settings.database_url.startswith(prefix):
        raise ValueError("Phase 10 workflow store requires SQLite.")
    return Path(settings.database_url.removeprefix(prefix))


def _audit_path() -> Path:
    root = Path(__file__).resolve().parents[3]
    return Path(os.getenv("FORTIFY_AUDIT_LOG", root / "artifacts" / "phase8" / "dashboard_audit.jsonl"))


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def initialize_workflow_store() -> None:
    path = _db_path(); path.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS workflow_items (
            workflow_item_id TEXT PRIMARY KEY, person_id TEXT NOT NULL, recommendation_date TEXT NOT NULL,
            risk_band TEXT NOT NULL, recommended_action TEXT NOT NULL, priority TEXT NOT NULL,
            feasibility_status TEXT NOT NULL, constraint_flags TEXT NOT NULL, rationale TEXT NOT NULL,
            requires_human_review INTEGER NOT NULL, model_version TEXT NOT NULL, policy_version TEXT NOT NULL,
            feasibility_policy_version TEXT NOT NULL, workflow_state TEXT NOT NULL,
            last_transition_at TEXT, last_actor_role TEXT, last_reason_code TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS workflow_audit_events (
            event_id TEXT PRIMARY KEY, workflow_item_id TEXT NOT NULL, person_id TEXT NOT NULL,
            recommendation_date TEXT NOT NULL, previous_state TEXT NOT NULL, new_state TEXT NOT NULL,
            actor_role TEXT NOT NULL, purpose TEXT NOT NULL, timestamp TEXT NOT NULL, reason_code TEXT NOT NULL,
            model_version TEXT NOT NULL, policy_version TEXT NOT NULL, feasibility_policy_version TEXT NOT NULL,
            workflow_policy_version TEXT NOT NULL,
            FOREIGN KEY (workflow_item_id) REFERENCES workflow_items(workflow_item_id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS workflow_support_events (
            support_event_id TEXT PRIMARY KEY, workflow_item_id TEXT NOT NULL, person_id TEXT NOT NULL,
            support_action TEXT NOT NULL, completed_at TEXT NOT NULL, actor_role TEXT NOT NULL,
            FOREIGN KEY (workflow_item_id) REFERENCES workflow_items(workflow_item_id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS workflow_feedback (
            feedback_id TEXT PRIMARY KEY, workflow_item_id TEXT NOT NULL, support_event_id TEXT NOT NULL,
            person_id TEXT NOT NULL, helpfulness INTEGER NOT NULL, comment TEXT,
            follow_up_requested INTEGER NOT NULL, submitted_at TEXT NOT NULL, recorded_by_role TEXT NOT NULL,
            FOREIGN KEY (workflow_item_id) REFERENCES workflow_items(workflow_item_id),
            FOREIGN KEY (support_event_id) REFERENCES workflow_support_events(support_event_id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS workflow_followups (
            followup_id TEXT PRIMARY KEY, workflow_item_id TEXT NOT NULL, support_event_id TEXT NOT NULL,
            person_id TEXT NOT NULL, scheduled_for TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL, created_by_role TEXT NOT NULL, last_updated_at TEXT NOT NULL,
            completed_at TEXT, completed_by_role TEXT,
            FOREIGN KEY (workflow_item_id) REFERENCES workflow_items(workflow_item_id),
            FOREIGN KEY (support_event_id) REFERENCES workflow_support_events(support_event_id))""")
        # Safe migrations for databases created by Phase 10 before the expanded lifecycle.
        _ensure_column(conn, "workflow_items", "support_completed_at", "TEXT")
        _ensure_column(conn, "workflow_items", "support_completed_by_role", "TEXT")
        _ensure_column(conn, "workflow_items", "active_support_event_id", "TEXT")
        _ensure_column(conn, "workflow_items", "active_followup_id", "TEXT")
        _ensure_column(conn, "workflow_items", "feedback_submitted", "INTEGER NOT NULL DEFAULT 0")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_items_pending ON workflow_items(workflow_state, recommendation_date, priority, workflow_item_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_audit_item ON workflow_audit_events(workflow_item_id, timestamp, event_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_followups_status ON workflow_followups(status, scheduled_for, followup_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_feedback_item ON workflow_feedback(workflow_item_id, submitted_at, feedback_id)")
        conn.commit()


def _workflow_id(person_id: str, date: str) -> str:
    digest = hashlib.sha256(f"{person_id}|{date}".encode()).hexdigest()[:16]
    return f"WF-{digest}"


def _load_decisions() -> pd.DataFrame:
    global _DECISION_CACHE
    root = Path(__file__).resolve().parents[3]
    data_dir = Path(os.getenv("FORTIFY_DATA_DIR", root / "data" / "generated"))
    with _DECISION_CACHE_LOCK:
        signature = _data_signature(data_dir)
        if _DECISION_CACHE is not None and _DECISION_CACHE[0] == signature:
            return _DECISION_CACHE[1].copy()
        rec = pd.read_csv(data_dir / "intervention_recommendations.csv", usecols=[
            "person_id", "date", "welfare_risk_probability", "risk_band", "recommended_action", "priority", "rationale",
            "requires_human_review", "model_version", "policy_version"])
        feas = pd.read_csv(data_dir / "intervention_feasibility.csv", usecols=[
            "person_id", "date", "recommended_action", "feasibility_status", "constraint_flags",
            "requires_human_review", "feasibility_policy_version"])
        for df in (rec, feas):
            df["date"] = pd.to_datetime(df["date"], errors="raise").dt.strftime("%Y-%m-%d")
        merged = rec.merge(feas, on=["person_id", "date", "recommended_action"], how="inner",
                           validate="one_to_one", suffixes=("_rec", "_feas"))
        _DECISION_CACHE = (signature, merged.copy())
        return merged


def ensure_workflow_items() -> None:
    initialize_workflow_store(); data = _load_decisions()
    with _connect() as conn:
        existing = {row[0] for row in conn.execute("SELECT workflow_item_id FROM workflow_items")}
        rows = []
        for r in data.itertuples(index=False):
            item_id = _workflow_id(str(r.person_id), str(r.date))
            if item_id in existing: continue
            action = str(r.recommended_action)
            if action not in ALLOWED_ACTIONS: raise ValueError(f"Unsupported intervention action: {action}")
            rows.append((item_id, str(r.person_id), str(r.date), str(r.risk_band), action, str(r.priority),
                         str(r.feasibility_status), str(r.constraint_flags or ""), str(r.rationale),
                         int(bool(r.requires_human_review_feas)), str(r.model_version), str(r.policy_version),
                         str(r.feasibility_policy_version), "NEW", None, None, None, None, None, None, None, 0))
        conn.executemany("""INSERT OR IGNORE INTO workflow_items
            (workflow_item_id, person_id, recommendation_date, risk_band, recommended_action, priority,
             feasibility_status, constraint_flags, rationale, requires_human_review, model_version, policy_version,
             feasibility_policy_version, workflow_state, last_transition_at, last_actor_role, last_reason_code,
             support_completed_at, support_completed_by_role, active_support_event_id, active_followup_id, feedback_submitted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows)
        conn.commit()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "workflow_item_id": row["workflow_item_id"], "person_id": row["person_id"], "date": row["recommendation_date"],
        "risk_band": row["risk_band"], "recommended_action": row["recommended_action"], "priority": row["priority"],
        "feasibility_status": row["feasibility_status"], "constraint_flags": row["constraint_flags"],
        "rationale": row["rationale"], "requires_human_review": bool(row["requires_human_review"]),
        "model_version": row["model_version"], "policy_version": row["policy_version"],
        "feasibility_policy_version": row["feasibility_policy_version"], "workflow_state": row["workflow_state"],
        "last_transition_at": row["last_transition_at"], "last_actor_role": row["last_actor_role"],
        "last_reason_code": row["last_reason_code"], "support_completed_at": row["support_completed_at"],
        "support_completed_by_role": row["support_completed_by_role"], "active_support_event_id": row["active_support_event_id"],
        "active_followup_id": row["active_followup_id"], "feedback_submitted": bool(row["feedback_submitted"]),
    }


def _trend_lookup() -> dict[tuple[str, str], str]:
    decisions = _load_decisions()[["person_id", "date", "welfare_risk_probability", "risk_band"]].copy()
    decisions["date"] = decisions["date"].astype(str)
    decisions = decisions.sort_values(["person_id", "date"])
    lookup: dict[tuple[str, str], str] = {}
    for pid, group in decisions.groupby("person_id", sort=False):
        previous_prob = None; previous_band = None
        for rec in group.itertuples(index=False):
            if previous_prob is None:
                value = "RISING" if str(rec.risk_band) == "HIGH" else "STABLE"
            else:
                delta = float(rec.welfare_risk_probability) - previous_prob
                value = "RISING" if delta > 0.015 or (str(rec.risk_band) == "HIGH" and previous_band != "HIGH") else "IMPROVING" if delta < -0.015 else "STABLE"
            lookup[(str(pid), str(rec.date))] = value
            previous_prob = float(rec.welfare_risk_probability); previous_band = str(rec.risk_band)
    return lookup


def list_items(*, pending_only: bool = True, limit: int = 50) -> list[dict[str, Any]]:
    ensure_workflow_items(); limit = max(1, min(limit, 200)); trend_lookup = _trend_lookup()
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        states = "'NEW','ACKNOWLEDGED','IN_REVIEW','SUPPORT_PLANNED','DEFERRED'"
        sql = f"SELECT * FROM workflow_items WHERE workflow_state IN ({states})" if pending_only else "SELECT * FROM workflow_items"
        sql += " ORDER BY recommendation_date DESC, CASE priority WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 WHEN 'LOW' THEN 2 ELSE 3 END, workflow_item_id LIMIT ?"
        rows = conn.execute(sql, (limit,)).fetchall()
    items = [_row_to_dict(r) for r in rows]
    for item in items: item["trend"] = trend_lookup.get((str(item["person_id"]), str(item["date"])), "STABLE")
    return items


def get_item(workflow_item_id: str) -> dict[str, Any] | None:
    ensure_workflow_items()
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM workflow_items WHERE workflow_item_id = ?", (workflow_item_id,)).fetchone()
        if not row: return None
        item = _row_to_dict(row)
    item["history"] = get_history(workflow_item_id)
    item["support_event"] = get_support_event(workflow_item_id)
    item["feedback"] = get_feedback(workflow_item_id)
    item["followup"] = get_followup(workflow_item_id)
    return item


def get_history(workflow_item_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("""SELECT event_id, workflow_item_id, person_id, recommendation_date,
            previous_state, new_state, actor_role, purpose, timestamp, reason_code, model_version,
            policy_version, feasibility_policy_version, workflow_policy_version
            FROM workflow_audit_events WHERE workflow_item_id=? ORDER BY timestamp ASC, event_id ASC""", (workflow_item_id,)).fetchall()
    return [{"event_id":r[0],"workflow_item_id":r[1],"person_id":r[2],"date":r[3],"previous_state":r[4],"new_state":r[5],
             "actor_role":r[6],"purpose":r[7],"timestamp":r[8],"reason_code":r[9],"model_version":r[10],
             "policy_version":r[11],"feasibility_policy_version":r[12],"workflow_policy_version":r[13]} for r in rows]


def get_support_event(workflow_item_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("""SELECT support_event_id, workflow_item_id, person_id, support_action, completed_at, actor_role
            FROM workflow_support_events WHERE workflow_item_id=? ORDER BY completed_at DESC, support_event_id DESC LIMIT 1""", (workflow_item_id,)).fetchone()
    if not row: return None
    return {"support_event_id":row[0],"workflow_item_id":row[1],"person_id":row[2],"support_action":row[3],"completed_at":row[4],"actor_role":row[5]}


def get_feedback(workflow_item_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("""SELECT feedback_id, support_event_id, helpfulness, comment, follow_up_requested, submitted_at, recorded_by_role
            FROM workflow_feedback WHERE workflow_item_id=? ORDER BY submitted_at DESC, feedback_id DESC LIMIT 1""", (workflow_item_id,)).fetchone()
    if not row: return None
    return {"feedback_id":row[0],"support_event_id":row[1],"helpfulness":int(row[2]),"comment":row[3],"follow_up_requested":bool(row[4]),"submitted_at":row[5],"recorded_by_role":row[6]}


def get_followup(workflow_item_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("""SELECT followup_id, support_event_id, scheduled_for, status, created_at, created_by_role,
            last_updated_at, completed_at, completed_by_role FROM workflow_followups
            WHERE workflow_item_id=? ORDER BY last_updated_at DESC, followup_id DESC LIMIT 1""", (workflow_item_id,)).fetchone()
    if not row: return None
    return {"followup_id":row[0],"support_event_id":row[1],"scheduled_for":row[2],"status":row[3],"created_at":row[4],"created_by_role":row[5],"last_updated_at":row[6],"completed_at":row[7],"completed_by_role":row[8]}


def _authorize_transition(actor_role: str, purpose: str, config: WorkflowPolicyConfig) -> None:
    decision = authorize(actor_role, purpose)
    if not decision.allowed or actor_role != config.review_role or purpose != config.review_purpose:
        raise PermissionError("Individual workflow transitions require welfare-support authorization.")


def _write_external_audit(event_type: str, actor_role: str, purpose: str, resource: str, timestamp: str, details: dict[str, Any]) -> None:
    AuditLog(_audit_path()).append(AuditEvent(event_type, actor_role, purpose, "ALLOWED", resource, timestamp, details))


def transition_item(workflow_item_id: str, *, new_state: str, actor_role: str, purpose: str, reason_code: str,
                    config: WorkflowPolicyConfig | None = None) -> dict[str, Any]:
    config = config or WorkflowPolicyConfig(); _authorize_transition(actor_role, purpose, config)
    if new_state not in WORKFLOW_STATES: raise ValueError(f"Unknown workflow state: {new_state}")
    if not reason_code.strip(): raise ValueError("reason_code is required for workflow transitions")
    ensure_workflow_items(); now = datetime.now(timezone.utc).isoformat(); support_created = None
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE"); conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM workflow_items WHERE workflow_item_id=?", (workflow_item_id,)).fetchone()
        if not row: raise KeyError("Workflow item not found")
        current = str(row["workflow_state"])
        if new_state not in TRANSITIONS[current]: raise ValueError(f"Invalid workflow transition: {current} -> {new_state}")
        event_id = f"WFE-{hashlib.sha256(f'{workflow_item_id}|{current}|{new_state}|{now}'.encode()).hexdigest()[:20]}"
        if new_state in {"SUPPORT_COMPLETED", "COMPLETED"}:
            support_created = f"SUP-{hashlib.sha256(f'{workflow_item_id}|{now}'.encode()).hexdigest()[:20]}"
            conn.execute("""INSERT INTO workflow_support_events
                (support_event_id, workflow_item_id, person_id, support_action, completed_at, actor_role)
                VALUES (?, ?, ?, ?, ?, ?)""", (support_created, workflow_item_id, row["person_id"], row["recommended_action"], now, actor_role))
        conn.execute("""UPDATE workflow_items SET workflow_state=?,last_transition_at=?,last_actor_role=?,last_reason_code=?,
            support_completed_at=COALESCE(?, support_completed_at), support_completed_by_role=COALESCE(?, support_completed_by_role),
            active_support_event_id=COALESCE(?, active_support_event_id) WHERE workflow_item_id=?""",
                     (new_state, now, actor_role, reason_code, now if support_created else None, actor_role if support_created else None, support_created, workflow_item_id))
        conn.execute("""INSERT INTO workflow_audit_events
          (event_id,workflow_item_id,person_id,recommendation_date,previous_state,new_state,actor_role,purpose,timestamp,reason_code,model_version,policy_version,feasibility_policy_version,workflow_policy_version)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (event_id,workflow_item_id,row["person_id"],row["recommendation_date"],current,new_state,actor_role,purpose,now,reason_code,row["model_version"],row["policy_version"],row["feasibility_policy_version"],config.workflow_policy_version))
        conn.commit()
    _write_external_audit("WORKFLOW_TRANSITION", actor_role, purpose, f"/api/workflow/{workflow_item_id}", now,
                          {"event_id":event_id,"workflow_item_id":workflow_item_id,"person_id":row["person_id"],"recommendation_date":row["recommendation_date"],
                           "previous_state":current,"new_state":new_state,"reason_code":reason_code,"model_version":row["model_version"],
                           "policy_version":row["policy_version"],"feasibility_policy_version":row["feasibility_policy_version"],"workflow_policy_version":config.workflow_policy_version})
    return get_item(workflow_item_id) or {}


def _require_welfare_actor(actor_role: str, purpose: str) -> None:
    if authorize(actor_role, purpose).allowed is not True or actor_role != SecurityRole.WELFARE_OFFICER.value or purpose != AccessPurpose.WELFARE_SUPPORT.value:
        raise PermissionError("Welfare-support authorization is required.")


def record_feedback(workflow_item_id: str, *, helpfulness: int, comment: str | None, follow_up_requested: bool,
                    actor_role: str, purpose: str) -> dict[str, Any]:
    _require_welfare_actor(actor_role, purpose); ensure_workflow_items()
    if not 1 <= helpfulness <= 5: raise ValueError("helpfulness must be between 1 and 5")
    item = get_item(workflow_item_id)
    if not item: raise KeyError("Workflow item not found")
    support = item.get("support_event")
    if not support: raise ValueError("Personnel feedback requires recorded support completion.")
    now = datetime.now(timezone.utc).isoformat(); fid = f"FB-{hashlib.sha256(f'{workflow_item_id}|{now}'.encode()).hexdigest()[:20]}"
    with _connect() as conn:
        conn.execute("INSERT INTO workflow_feedback(feedback_id,workflow_item_id,support_event_id,person_id,helpfulness,comment,follow_up_requested,submitted_at,recorded_by_role) VALUES (?,?,?,?,?,?,?,?,?)",
                     (fid,workflow_item_id,support["support_event_id"],item["person_id"],helpfulness,(comment or "").strip() or None,int(follow_up_requested),now,actor_role))
        conn.execute("UPDATE workflow_items SET feedback_submitted=1 WHERE workflow_item_id=?", (workflow_item_id,)); conn.commit()
    _write_external_audit("WORKFLOW_FEEDBACK_RECORDED", actor_role, purpose, f"/api/workflow/{workflow_item_id}/feedback", now,
                          {"feedback_id":fid,"workflow_item_id":workflow_item_id,"person_id":item["person_id"],"support_event_id":support["support_event_id"],"follow_up_requested":bool(follow_up_requested)})
    return get_item(workflow_item_id) or {}


def schedule_followup(workflow_item_id: str, scheduled_for: str, actor_role: str, purpose: str) -> dict[str, Any]:
    _require_welfare_actor(actor_role, purpose); ensure_workflow_items()
    try:
        when = datetime.fromisoformat(scheduled_for.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("scheduled_for must be an ISO-8601 datetime") from exc
    if when.tzinfo is None: raise ValueError("scheduled_for must include a timezone")
    item = get_item(workflow_item_id)
    if not item: raise KeyError("Workflow item not found")
    if item["workflow_state"] not in {"SUPPORT_COMPLETED", "FOLLOW_UP_SCHEDULED", "FOLLOW_UP_DUE"}:
        raise ValueError("Follow-up can only be scheduled after support completion.")
    support = item.get("support_event")
    if not support: raise ValueError("Follow-up requires a recorded support event.")
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute("SELECT followup_id FROM workflow_followups WHERE workflow_item_id=? AND status IN ('SCHEDULED','DUE') ORDER BY last_updated_at DESC LIMIT 1", (workflow_item_id,)).fetchone()
        if active:
            followup_id = active[0]
            conn.execute("UPDATE workflow_followups SET scheduled_for=?,status='SCHEDULED',last_updated_at=? WHERE followup_id=?", (when.astimezone(timezone.utc).isoformat(), now, followup_id))
            reason = "FOLLOW_UP_RESCHEDULED"
            event_id = f"WFE-{hashlib.sha256(f'{workflow_item_id}|FOLLOW_UP_RESCHEDULED|{now}'.encode()).hexdigest()[:20]}"
            conn.execute("""INSERT INTO workflow_audit_events(
                event_id,workflow_item_id,person_id,recommendation_date,previous_state,new_state,actor_role,purpose,
                timestamp,reason_code,model_version,policy_version,feasibility_policy_version,workflow_policy_version
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (event_id,workflow_item_id,item["person_id"],item["date"],item["workflow_state"],item["workflow_state"],
                 actor_role,purpose,now,reason,item["model_version"],item["policy_version"],
                 item["feasibility_policy_version"],WorkflowPolicyConfig().workflow_policy_version))
        else:
            followup_id = f"FU-{hashlib.sha256(f'{workflow_item_id}|{scheduled_for}|{now}'.encode()).hexdigest()[:20]}"
            conn.execute("INSERT INTO workflow_followups(followup_id,workflow_item_id,support_event_id,person_id,scheduled_for,status,created_at,created_by_role,last_updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                         (followup_id,workflow_item_id,support["support_event_id"],item["person_id"],when.astimezone(timezone.utc).isoformat(),"SCHEDULED",now,actor_role,now))
            reason = "FOLLOW_UP_SCHEDULED"
            event_id = f"WFE-{hashlib.sha256(f'{workflow_item_id}|FOLLOW_UP_SCHEDULED|{now}'.encode()).hexdigest()[:20]}"
            conn.execute("UPDATE workflow_items SET active_followup_id=?,workflow_state=?,last_transition_at=?,last_actor_role=?,last_reason_code=? WHERE workflow_item_id=?",
                         (followup_id,"FOLLOW_UP_SCHEDULED",now,actor_role,reason,workflow_item_id))
            conn.execute("INSERT INTO workflow_audit_events(event_id,workflow_item_id,person_id,recommendation_date,previous_state,new_state,actor_role,purpose,timestamp,reason_code,model_version,policy_version,feasibility_policy_version,workflow_policy_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (event_id,workflow_item_id,item["person_id"],item["date"],item["workflow_state"],"FOLLOW_UP_SCHEDULED",actor_role,purpose,now,reason,item["model_version"],item["policy_version"],item["feasibility_policy_version"],WorkflowPolicyConfig().workflow_policy_version))
        conn.commit()
    _write_external_audit("WORKFLOW_FOLLOWUP", actor_role, purpose, f"/api/workflow/{workflow_item_id}/follow-up", now,
                          {"workflow_item_id":workflow_item_id,"person_id":item["person_id"],"followup_id":followup_id,"scheduled_for":when.astimezone(timezone.utc).isoformat(),"reason_code":reason,**({"event_id":event_id} if event_id else {})})
    return get_item(workflow_item_id) or {}


def list_followups(status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    ensure_workflow_items(); limit = max(1, min(limit, 200)); now = datetime.now(timezone.utc)
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""SELECT f.*, w.risk_band, w.recommended_action, w.priority, w.feasibility_status,
            w.constraint_flags, w.last_actor_role, w.workflow_state, s.completed_at AS support_completed_at,
            s.support_action, s.actor_role AS support_actor_role
            FROM workflow_followups f
            JOIN workflow_items w ON w.workflow_item_id=f.workflow_item_id
            JOIN workflow_support_events s ON s.support_event_id=f.support_event_id
            ORDER BY f.scheduled_for ASC, f.followup_id ASC LIMIT ?""", (limit,)).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        scheduled = datetime.fromisoformat(str(r["scheduled_for"]).replace("Z", "+00:00"))
        display_status = "COMPLETED" if r["status"] == "COMPLETED" else "DUE" if scheduled <= now else "SCHEDULED"
        if status and display_status != status: continue
        out.append({
            "followup_id": r["followup_id"], "workflow_item_id": r["workflow_item_id"], "support_event_id": r["support_event_id"],
            "person_id": r["person_id"], "scheduled_for": r["scheduled_for"], "status": display_status,
            "created_at": r["created_at"], "created_by_role": r["created_by_role"], "last_updated_at": r["last_updated_at"],
            "completed_at": r["completed_at"], "completed_by_role": r["completed_by_role"], "risk_band": r["risk_band"],
            "recommended_action": r["recommended_action"], "priority": r["priority"], "feasibility_status": r["feasibility_status"],
            "constraint_flags": r["constraint_flags"], "workflow_state": r["workflow_state"],
            "support_completed_at": r["support_completed_at"], "support_action": r["support_action"],
            "support_actor_role": r["support_actor_role"], "follow_up_requested": False,
        })
    return out


def complete_followup(followup_id: str, actor_role: str, purpose: str) -> dict[str, Any]:
    _require_welfare_actor(actor_role, purpose); ensure_workflow_items(); now=datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        row=conn.execute("SELECT f.*,w.* FROM workflow_followups f JOIN workflow_items w ON w.workflow_item_id=f.workflow_item_id WHERE f.followup_id=?",(followup_id,)).fetchone()
        if not row: raise KeyError("Follow-up not found")
        workflow_id=row[1]; current=row["workflow_state"]
        if row[5] == "COMPLETED": raise ValueError("Follow-up is already completed.")
        if current not in {"FOLLOW_UP_SCHEDULED","FOLLOW_UP_DUE"}: raise ValueError("Workflow is not in a follow-up state.")
        conn.execute("UPDATE workflow_followups SET status='COMPLETED',completed_at=?,completed_by_role=?,last_updated_at=? WHERE followup_id=?",(now,actor_role,now,followup_id))
        conn.execute("UPDATE workflow_items SET workflow_state='FOLLOW_UP_COMPLETED',last_transition_at=?,last_actor_role=?,last_reason_code=? WHERE workflow_item_id=?",(now,actor_role,"FOLLOW_UP_COMPLETED_BY_HUMAN",workflow_id))
        event_id=f"WFE-{hashlib.sha256(f'{workflow_id}|FOLLOW_UP_COMPLETED|{now}'.encode()).hexdigest()[:20]}"
        conn.execute("INSERT INTO workflow_audit_events(event_id,workflow_item_id,person_id,recommendation_date,previous_state,new_state,actor_role,purpose,timestamp,reason_code,model_version,policy_version,feasibility_policy_version,workflow_policy_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (event_id,workflow_id,row["person_id"],row["recommendation_date"],current,"FOLLOW_UP_COMPLETED",actor_role,purpose,now,"FOLLOW_UP_COMPLETED_BY_HUMAN",row["model_version"],row["policy_version"],row["feasibility_policy_version"],WorkflowPolicyConfig().workflow_policy_version))
        conn.commit()
    _write_external_audit("WORKFLOW_FOLLOWUP_COMPLETED", actor_role, purpose, f"/api/workflow/{workflow_id}/follow-up", now,{"event_id":event_id,"workflow_item_id":workflow_id,"person_id":row["person_id"],"followup_id":followup_id})
    return get_item(workflow_id) or {}
