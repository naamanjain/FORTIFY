from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

import app.services.workflow as workflow
from app.api.routes import dashboard as dashboard_route
from app.security.rbac import UnitScope as _UnitScope

# Direct (non-HTTP) service callers must state an explicit scope.
_SCRIPT_SCOPE = _UnitScope.script()


def minimal_decisions() -> pd.DataFrame:
    return pd.DataFrame([{
        "person_id": "P-0001", "date": "2026-06-29", "risk_band": "HIGH",
        "recommended_action": "PRIORITY_WELFARE_REVIEW", "priority": "HIGH",
        "rationale": "Associated operational signals support human welfare review.",
        "requires_human_review": True, "model_version": "phase4-v1",
        "policy_version": "phase6-v1", "feasibility_status": "FEASIBLE",
        "constraint_flags": "", "requires_human_review_feas": True,
        "feasibility_policy_version": "phase7-v1",
    }])


def prepare_db(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workflow, "_DECISION_CACHE", None)
    monkeypatch.setattr(workflow, "_db_path", lambda: path)
    monkeypatch.setattr(workflow, "_load_decisions", lambda: minimal_decisions())
    workflow.initialize_workflow_store()
    workflow.ensure_workflow_items()


def test_workflow_store_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "workflow.db"
    prepare_db(db, monkeypatch)
    workflow.ensure_workflow_items()
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM workflow_items").fetchone()[0] == 1
        indices = {row[1] for row in conn.execute("PRAGMA index_list(workflow_items)")}
        assert "idx_workflow_items_pending" in indices


def test_concurrent_transition_allows_only_one_valid_state_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "workflow.db"
    audit = tmp_path / "audit.jsonl"
    prepare_db(db, monkeypatch)
    monkeypatch.setattr(workflow, "_audit_path", lambda: audit)
    import threading
    results: list[object] = []
    barrier = threading.Barrier(2)

    def run() -> None:
        barrier.wait()
        try:
            results.append(workflow.transition_item(
                workflow._workflow_id("P-0001", "2026-06-29"),
                new_state="ACKNOWLEDGED", actor_role="WELFARE_OFFICER",
                purpose="WELFARE_SUPPORT", reason_code="ACKNOWLEDGED_FOR_WELFARE_REVIEW",
                unit_scope=_SCRIPT_SCOPE))
        except Exception as exc:  # exactly one runner should lose the valid transition race
            results.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert all(not thread.is_alive() for thread in threads)
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1
    assert workflow.get_item(workflow._workflow_id("P-0001", "2026-06-29"),
                             unit_scope=_SCRIPT_SCOPE)["workflow_state"] == "ACKNOWLEDGED"


def test_audit_chain_is_fail_closed_when_tampered(tmp_path: Path) -> None:
    from app.security.audit import AuditEvent, AuditLog
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append(AuditEvent("ACCESS", "WELFARE_OFFICER", "WELFARE_SUPPORT", "ALLOWED", "resource", "2026-01-01T00:00:00Z", {}))
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    record = lines[0].replace('"ALLOWED"', '"DENIED"')
    (tmp_path / "audit.jsonl").write_text(record + "\n")
    assert not log.verify_chain()


def test_generated_audit_key_is_read_verbatim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A key containing whitespace bytes must not be stripped on reload.

    The key is binary. Reading it with ``.strip()`` shortened a generated key
    that began or ended with a whitespace byte, so the anchor signature written
    on the first append failed verification from the next read onward.
    """
    from app.security import audit as audit_module
    from app.security.audit import AuditEvent, AuditLog

    # Force the generated key to end with a byte .strip() removes.
    monkeypatch.setattr(audit_module.os, "urandom", lambda size: b"k" * (size - 1) + b"\n")
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append(AuditEvent("ACCESS", "WELFARE_OFFICER", "WELFARE_SUPPORT", "ALLOWED",
                          "resource", "2026-01-01T00:00:00Z", {}))
    assert len(AuditLog(path)._key()) == 32
    assert AuditLog(path).verify_chain()


def test_mutations_recheck_scope_on_the_locked_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Feedback and follow-up writes cannot rely on an earlier scoped read.

    The pre-read is deliberately bypassed here to model a case that moves units
    (or a stale authorization) between the read and the write. Only the check
    on the locked row inside the transaction can stop the write.
    """
    from app.security.rbac import UnitScope

    db = tmp_path / "workflow.db"
    prepare_db(db, monkeypatch)
    monkeypatch.setattr(workflow, "_audit_path", lambda: tmp_path / "audit.jsonl")
    item_id = workflow._workflow_id("P-0001", "2026-06-29")
    for state in ("ACKNOWLEDGED", "IN_REVIEW", "SUPPORT_PLANNED", "SUPPORT_COMPLETED"):
        workflow.transition_item(item_id, new_state=state, actor_role="WELFARE_OFFICER",
                                 purpose="WELFARE_SUPPORT", reason_code="TEST",
                                 unit_scope=_SCRIPT_SCOPE)
    original_unit = workflow._personnel_unit_map()["P-0001"]
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE workflow_items SET unit_id='U-OTHER' WHERE workflow_item_id=?", (item_id,))

    scope = UnitScope(units=frozenset({original_unit}), source="claims")
    original_get_item = workflow.get_item
    monkeypatch.setattr(workflow, "get_item",
                        lambda wid, *, unit_scope=None: original_get_item(wid, unit_scope=_SCRIPT_SCOPE))
    with pytest.raises(KeyError):
        workflow.transition_item(item_id, new_state="FOLLOW_UP_SCHEDULED",
                                 actor_role="WELFARE_OFFICER", purpose="WELFARE_SUPPORT",
                                 reason_code="SCOPE-RECHECK", unit_scope=scope)
    with pytest.raises(KeyError):
        workflow.record_feedback(item_id, helpfulness=4, comment=None, follow_up_requested=False,
                                 actor_role="WELFARE_OFFICER", purpose="WELFARE_SUPPORT",
                                 unit_scope=scope)
    with pytest.raises(KeyError):
        workflow.schedule_followup(item_id, "2026-07-01T09:00:00+00:00",
                                   actor_role="WELFARE_OFFICER", purpose="WELFARE_SUPPORT",
                                   unit_scope=scope)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT workflow_state FROM workflow_items WHERE workflow_item_id=?",
                            (item_id,)).fetchone()[0] == "SUPPORT_COMPLETED"
        assert conn.execute("SELECT COUNT(*) FROM workflow_feedback").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM workflow_followups").fetchone()[0] == 0


def test_rows_without_unit_attribution_are_never_listed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing unit metadata cannot fall through an all-units query."""
    from app.security.rbac import UnitScope

    db = tmp_path / "workflow.db"
    prepare_db(db, monkeypatch)
    item_id = workflow._workflow_id("P-0001", "2026-06-29")
    # Keep ensure_workflow_items from backfilling the unit from personnel.csv.
    monkeypatch.setattr(workflow, "ensure_workflow_items", lambda: None)
    monkeypatch.setattr(workflow, "_trend_lookup", lambda: {})
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE workflow_items SET unit_id=NULL WHERE workflow_item_id=?", (item_id,))
    all_units = UnitScope(all_units=True, source="demo-all")
    assert workflow.list_items(pending_only=True, limit=10, unit_scope=all_units) == []
    assert workflow.get_item(item_id, unit_scope=all_units) is None


def test_sqlite_foreign_key_hardening(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "workflow.db"
    prepare_db(db, monkeypatch)
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("""INSERT INTO workflow_audit_events(
                event_id,workflow_item_id,person_id,recommendation_date,previous_state,new_state,actor_role,purpose,timestamp,reason_code,
                model_version,policy_version,feasibility_policy_version,workflow_policy_version)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                "WFE-orphan", "WF-missing", "P-9999", "2026-06-29", "NEW", "ACKNOWLEDGED",
                "WELFARE_OFFICER", "WELFARE_SUPPORT", "2026-06-29T00:00:00Z", "TEST",
                "phase4", "phase6", "phase7", "phase10"))


def test_dashboard_cache_invalidates_when_source_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rec = tmp_path / "intervention_recommendations.csv"
    feas = tmp_path / "intervention_feasibility.csv"
    base_rec = pd.DataFrame([{
        "person_id":"P-0001","date":"2026-06-29","welfare_risk_probability":0.4,"risk_band":"MODERATE",
        "threshold_decision":"NO_ALERT","contributing_signals":"", "recommended_action":"RECOVERY_SUPPORT",
        "priority":"MEDIUM","requires_human_review":True,"policy_version":"phase6-v1","model_version":"phase4-v1"}])
    base_feas = pd.DataFrame([{
        "person_id":"P-0001","date":"2026-06-29","recommended_action":"RECOVERY_SUPPORT","feasibility_status":"FEASIBLE",
        "constraint_flags":"","adjustment_recommendation":"","requires_human_review":True,"feasibility_policy_version":"phase7-v1"}])
    base_rec.to_csv(rec,index=False); base_feas.to_csv(feas,index=False)
    monkeypatch.setattr(dashboard_route, "DATA_DIR", tmp_path)
    dashboard_route._SUMMARY_CACHE.clear(); dashboard_route._SUMMARY_SIGNATURE = None
    first = dashboard_route._dashboard_frame()
    base_rec.loc[0,"welfare_risk_probability"] = 0.9
    base_rec.loc[0,"risk_band"] = "HIGH"
    base_rec.to_csv(rec,index=False)
    second = dashboard_route._dashboard_frame()
    assert float(first.iloc[0]["welfare_risk_probability"]) == 0.4
    assert float(second.iloc[0]["welfare_risk_probability"]) == 0.9
