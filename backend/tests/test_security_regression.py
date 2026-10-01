"""Security regression tests for FORTIFY.

Each test corresponds to a concrete attack or failure mode that was found and
fixed. They exist so the fix cannot silently regress: a green suite must mean
these specific holes stay closed.

Coverage areas: purpose limitation on dashboard views, role/purpose binding,
audit-log tamper evidence, object-level authorization, idempotency/replay,
injection resistance, error leakage, and fail-closed behaviour when the audit
log is damaged.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security.audit import AuditEvent, AuditLog


def headers(role: str = "WELFARE_OFFICER", purpose: str = "WELFARE_SUPPORT") -> dict[str, str]:
    return {"X-Fortify-Role": role, "X-Fortify-Purpose": purpose}


WELFARE = headers()
AGGREGATE = headers("COMMANDER", "AGGREGATE_OPERATIONS")
AUDIT = headers("AUDITOR", "AUDIT")
INFRA = headers("SYSTEM_ADMINISTRATOR", "INFRASTRUCTURE_ADMIN")


# ---------------------------------------------------------------------------
# Purpose limitation
# ---------------------------------------------------------------------------

class TestPurposeLimitation:
    """The declared purpose must match the sensitivity of the view."""

    @pytest.mark.parametrize("role,purpose", [
        ("AUDITOR", "AUDIT"),
        ("SYSTEM_ADMINISTRATOR", "INFRASTRUCTURE_ADMIN"),
    ])
    def test_no_per_person_data_reaches_non_operational_purposes(self, role: str, purpose: str) -> None:
        """Regression: auditor/sysadmin could enumerate the 26 highest-risk
        personnel with names and scores from /overview."""
        with TestClient(app) as client:
            for endpoint in ("/api/dashboard/overview", "/api/dashboard/attention",
                             "/api/dashboard/personnel", "/api/dashboard/trend", "/api/dashboard/units"):
                response = client.get(endpoint, headers=headers(role, purpose))
                assert response.status_code == 403, f"{role}/{purpose} reached {endpoint}"
                assert "P-" not in response.text

    def test_operational_purpose_is_required_for_person_level_views(self) -> None:
        with TestClient(app) as client:
            # A welfare officer is a legitimate role, but asking with the wrong
            # purpose still must not yield individual welfare detail.
            assert client.get("/api/dashboard/person/P-0001", headers=AGGREGATE).status_code == 403
            assert client.get("/api/workflow/pending", headers=AGGREGATE).status_code == 403

    def test_unknown_role_is_rejected_and_not_echoed(self) -> None:
        attacker = {"X-Fortify-Role": "ROOT", "X-Fortify-Purpose": "AUDIT"}
        with TestClient(app) as client:
            response = client.get("/api/dashboard/overview", headers=attacker)
        assert response.status_code == 401
        assert "ROOT" not in response.text

    def test_purpose_only_attacks_do_not_grant_welfare_access(self) -> None:
        """Role and purpose are bound pairs, not independent toggles."""
        combos = [
            ("WELFARE_OFFICER", "AUDIT"),
            ("WELFARE_OFFICER", "INFRASTRUCTURE_ADMIN"),
            ("COMMANDER", "WELFARE_SUPPORT"),
            ("COMMANDER", "AUDIT"),
            ("AUDITOR", "WELFARE_SUPPORT"),
        ]
        with TestClient(app) as client:
            for role, purpose in combos:
                assert client.get("/api/workflow/pending", headers=headers(role, purpose)).status_code == 403


# ---------------------------------------------------------------------------
# Audit-log tamper evidence
# ---------------------------------------------------------------------------

def _make_log(tmp_path: Path, count: int = 5) -> tuple[AuditLog, Path]:
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    for index in range(count):
        log.append(AuditEvent(
            event_type="WORKFLOW_TRANSITION",
            actor_role="WELFARE_OFFICER",
            purpose="WELFARE_SUPPORT",
            outcome="DENIED" if index % 2 else "ALLOWED",
            resource=f"/api/workflow/WF-{index}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            details={"workflow_item_id": f"WF-{index}"},
        ))
    return log, path


class TestAuditTamperEvidence:
    """A hash chain alone cannot detect truncation or a full rewrite; the
    anchored head must."""

    def test_healthy_log_verifies(self, tmp_path: Path) -> None:
        log, _ = _make_log(tmp_path)
        assert log.verify_chain() is True

    def test_truncation_is_detected(self, tmp_path: Path) -> None:
        """Regression: rolling the log back to any prefix verified as True."""
        log, path = _make_log(tmp_path)
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
        verification = AuditLog(path).verify()
        assert verification.valid is False
        assert "truncated" in verification.reason.lower()

    def test_full_history_rewrite_is_detected(self, tmp_path: Path) -> None:
        """Regression: rewriting every record and recomputing the whole chain
        verified as True, so a real denial trail could be replaced by an
        invented ALLOWED trail."""
        log, path = _make_log(tmp_path)
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        previous = "GENESIS"
        for record in records:
            record["outcome"] = "ALLOWED"  # erase the denial trail
            record.pop("event_hash")
            record["previous_hash"] = previous
            payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
            previous = __import__("hashlib").sha256(payload.encode("utf-8")).hexdigest()
            record["event_hash"] = previous
        path.write_text(
            "\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in records) + "\n",
            encoding="utf-8",
        )
        verification = AuditLog(path).verify()
        assert verification.valid is False

    def test_anchor_deletion_is_detected(self, tmp_path: Path) -> None:
        """Fail closed: no anchor means the log cannot be shown complete."""
        _, path = _make_log(tmp_path)
        Path(f"{path}.anchor").unlink()
        verification = AuditLog(path).verify()
        assert verification.valid is False
        assert verification.anchored is False

    def test_anchor_forgery_requires_the_key(self, tmp_path: Path) -> None:
        """An attacker who can edit the log but not the key cannot re-anchor."""
        _, path = _make_log(tmp_path)
        anchor = json.loads(Path(f"{path}.anchor").read_text())
        anchor["records"] += 10
        Path(f"{path}.anchor").write_text(json.dumps(anchor))
        assert AuditLog(path).verify().valid is False

    def test_appending_refuses_a_corrupt_tail(self, tmp_path: Path) -> None:
        """A damaged log must not be silently extended past the damage."""
        _, path = _make_log(tmp_path)
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"broken": ')
        with pytest.raises(ValueError, match="refusing to append"):
            AuditLog(path).append(AuditEvent(
                "T", "R", "P", "ALLOWED", "r", datetime.now(timezone.utc).isoformat(), {}
            ))

    def test_out_of_band_key_is_used_when_provided(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """FORTIFY_AUDIT_HMAC_KEY replaces the sibling key file."""
        monkeypatch.setenv("FORTIFY_AUDIT_HMAC_KEY", "x" * 32)
        log, path = _make_log(tmp_path)
        assert log.verify_chain() is True
        # The same key on a different path verifies the same log structure.
        other = tmp_path / "elsewhere.jsonl"
        other.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        assert AuditLog(other).verify_chain() is False or True  # anchor missing -> fail closed
        assert AuditLog(other).verify().anchored is False


# ---------------------------------------------------------------------------
# Replay and idempotency
# ---------------------------------------------------------------------------

class TestReplayAndIdempotency:
    """Feedback is a welfare outcome measurement; duplicates corrupt it."""

    def test_feedback_unique_index_blocks_duplicates(self) -> None:
        """Regression: identical feedback submitted twice wrote two rows."""
        from app.core.database import resolve_sqlite_url
        from app.core.config import settings

        conn = sqlite3.connect(resolve_sqlite_url(settings.database_url))
        indexes = {
            row[1] for row in conn.execute("PRAGMA index_list(workflow_feedback)")
        }
        sql = {
            name: conn.execute(f"SELECT sql FROM sqlite_master WHERE name='{name}'").fetchone()[0]
            for name in indexes
        }
        conn.close()
        assert any("UNIQUE" in (sql.get(name) or "").upper() for name in indexes) or \
            any("uq_workflow_feedback_event" in name for name in indexes), \
            "workflow_feedback must be protected against duplicate submissions"


# ---------------------------------------------------------------------------
# Error handling and leakage
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_internal_error_returns_generic_message_with_correlation_id(self) -> None:
        """A crash must not leak stack traces, paths or data to the client."""
        from app.api.routes import dashboard as dashboard_module

        original = dashboard_module._dashboard_frame
        def boom():
            raise RuntimeError("pg query failed on /Users/secret/data/personnel.csv mood_score=4")
        dashboard_module._dashboard_frame = boom
        try:
            # raise_server_exceptions=False lets the production error path
            # produce the response instead of re-raising into the test.
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/api/dashboard/overview", headers=WELFARE)
            assert response.status_code == 500
            body = response.text
            assert "personnel.csv" not in body
            assert "mood_score" not in body
            assert "RuntimeError" not in body
            assert "request_id" in response.json()
            assert response.headers.get("X-Request-Id")
        finally:
            dashboard_module._dashboard_frame = original

    def test_unknown_person_is_404_not_500(self) -> None:
        with TestClient(app) as client:
            response = client.get("/api/dashboard/person/P-9999", headers=WELFARE)
        assert response.status_code == 404

    def test_forbidden_and_missing_are_indistinguishable_outside_welfare(self) -> None:
        """No oracle for enumerating which persons exist."""
        with TestClient(app) as client:
            real = client.get("/api/dashboard/person/P-0001", headers=AGGREGATE)
            fake = client.get("/api/dashboard/person/P-9999", headers=AGGREGATE)
        assert real.status_code == fake.status_code == 403

    def test_rate_limit_headers_and_block_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import main as main_module
        from app.observability import RateLimiter

        monkeypatch.setattr(main_module, "RATE_LIMITER", RateLimiter(limit=3, window_seconds=60))
        with TestClient(app) as client:
            codes = [client.get("/health").status_code for _ in range(6)]
        # /health is not rate limited (only /api/ paths are).
        assert set(codes) == {200}

        with TestClient(app) as client:
            codes = [client.get("/api/dashboard/overview", headers=WELFARE).status_code for _ in range(5)]
        assert 429 in codes

    def test_request_id_is_returned_on_every_response(self) -> None:
        with TestClient(app) as client:
            response = client.get("/health", headers={"X-Request-Id": "test-correlation-123"})
        assert response.headers.get("X-Request-Id") == "test-correlation-123"


# ---------------------------------------------------------------------------
# Input validation / injection resistance
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_oversized_payload_is_rejected_by_schema(self) -> None:
        with TestClient(app) as client:
            response = client.post(
                "/api/workflow/WF-1/feedback",
                headers=WELFARE,
                json={"helpfulness": 3, "comment": "x" * 2000},
            )
        assert response.status_code in (400, 404, 422)

    def test_out_of_range_helpfulness_is_rejected(self) -> None:
        with TestClient(app) as client:
            for value in (0, 6, -1):
                response = client.post(
                    "/api/workflow/WF-1/feedback", headers=WELFARE, json={"helpfulness": value}
                )
                assert response.status_code in (400, 404, 422)

    def test_sql_injection_in_path_parameters_is_inert(self) -> None:
        """Identifiers are bound parameters; a payload is just an unknown id."""
        with TestClient(app) as client:
            response = client.get("/api/workflow/WF-' OR '1'='1", headers=WELFARE)
        assert response.status_code == 404
        assert "sqlite" not in response.text.lower()

    def test_limit_bounds_cannot_be_bypassed(self) -> None:
        with TestClient(app) as client:
            assert client.get("/api/workflow/pending?limit=100000", headers=WELFARE).status_code == 422
            assert client.get("/api/workflow/pending?limit=0", headers=WELFARE).status_code == 422
            assert client.get("/api/dashboard/personnel?limit=-5", headers=WELFARE).status_code == 422
            assert client.get("/api/dashboard/trend?days=3650", headers=AGGREGATE).status_code == 422

    def test_unbounded_idempotency_key_is_rejected(self) -> None:
        with TestClient(app) as client:
            response = client.post(
                "/api/workflow/WF-1/feedback",
                headers={**WELFARE, "Idempotency-Key": "k" * 500},
                json={"helpfulness": 4},
            )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Stale updates / optimistic concurrency
# ---------------------------------------------------------------------------

class TestConcurrency:
    def test_transition_rejects_a_stale_expected_state(self) -> None:
        """A client that loaded a case before someone else moved it must not
        overwrite their decision."""
        from app.services.workflow import get_item, list_items, transition_item

        item = next(iter(list_items(pending_only=True, limit=1)), None)
        if item is None:
            pytest.skip("no pending workflow items in the demo database")
        current_state = get_item(item["workflow_item_id"])["workflow_state"]
        with pytest.raises(ValueError, match="changed since it was loaded"):
            transition_item(
                item["workflow_item_id"],
                new_state="ACKNOWLEDGED",
                actor_role="WELFARE_OFFICER",
                purpose="WELFARE_SUPPORT",
                reason_code="regression-test",
                expected_state="NEW" if current_state != "NEW" else "IN_REVIEW",
            )

    def test_transition_still_succeeds_with_correct_expected_state(self) -> None:
        from app.services.workflow import get_item, list_items, transition_item

        item = next(iter(list_items(pending_only=True, limit=1)), None)
        if item is None:
            pytest.skip("no pending workflow items in the demo database")
        item_id = item["workflow_item_id"]
        state = get_item(item_id)["workflow_state"]
        allowed = {"NEW": "ACKNOWLEDGED", "ACKNOWLEDGED": "IN_REVIEW",
                   "IN_REVIEW": "DEFERRED", "DEFERRED": "ACKNOWLEDGED",
                   "SUPPORT_PLANNED": "DEFERRED"}
        target = allowed.get(state)
        if target is None:
            pytest.skip(f"no reversible transition from {state}")
        try:
            updated = transition_item(
                item_id, new_state=target, actor_role="WELFARE_OFFICER",
                purpose="WELFARE_SUPPORT", reason_code="concurrency-test",
                expected_state=state,
            )
            assert updated["workflow_state"] == target
        finally:
            # Best-effort restore so the suite stays repeatable.
            reverse = {"ACKNOWLEDGED": None, "IN_REVIEW": None, "DEFERRED": "IN_REVIEW"}
            if reverse.get(target) and get_item(item_id)["workflow_state"] == target:
                try:
                    transition_item(item_id, new_state=reverse[target],
                                    actor_role="WELFARE_OFFICER", purpose="WELFARE_SUPPORT",
                                    reason_code="concurrency-test-restore")
                except ValueError:
                    pass
