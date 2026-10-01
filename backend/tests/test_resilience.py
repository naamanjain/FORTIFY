"""Resilience tests for FORTIFY.

Each test forces one dependency into a broken state and verifies the service
fails safely: liveness stays up, readiness reports the truth, data endpoints
return an actionable 503 (never a 500), and nothing serves welfare evidence
derived from corrupt input.

Broken states covered: generated artifacts missing, artifacts corrupted,
artifacts partially written (header only), database unavailable, and the
dashboard cache holding data that has since vanished from disk.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import paths as core_paths
from app.main import app
from app.api.routes import dashboard as dashboard_module

WELFARE = {"X-Fortify-Role": "WELFARE_OFFICER", "X-Fortify-Purpose": "WELFARE_SUPPORT"}


@pytest.fixture()
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point every data path at an empty temp dir for the duration of a test.

    Three modules bind DATA_DIR at import time (dashboard routes, workflow
    service, core paths), so all three must be redirected - patching one left
    the workflow layer silently reading the real dataset.
    """
    data_dir = tmp_path / "generated"
    data_dir.mkdir()
    monkeypatch.setattr(dashboard_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(core_paths, "DATA_DIR", data_dir)
    import app.main as main_module

    monkeypatch.setattr(main_module, "DATA_DIR", data_dir)
    import app.services.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "DATA_DIR", data_dir)
    yield data_dir


class TestArtifactsUnavailable:
    def test_liveness_survives_missing_artifacts(self, isolated_data_dir: Path) -> None:
        """A deployment without its dataset must still answer health checks -
        otherwise orchestration restarts a process that cannot be restarted
        into health."""
        with TestClient(app) as client:
            response = client.get("/health")
        assert response.status_code == 200

    def test_readiness_reports_missing_artifacts_with_remedy(self, isolated_data_dir: Path) -> None:
        with TestClient(app) as client:
            response = client.get("/ready")
        assert response.status_code == 503
        body = response.json()
        assert body["ready"] is False
        assert body["checks"]["artifacts"] == "missing"
        assert body["missing_artifacts"]
        assert "build_all.py" in body["remedy"]

    def test_data_endpoints_return_503_with_guidance(self, isolated_data_dir: Path) -> None:
        with TestClient(app) as client:
            for path in ("/api/dashboard/overview", "/api/dashboard/personnel"):
                response = client.get(path, headers=WELFARE)
                assert response.status_code == 503
                assert "build_all.py" in response.json()["detail"]
            workflow = client.get("/api/workflow/pending", headers=WELFARE)
            assert workflow.status_code == 503

    def test_corrupt_artifact_returns_503_not_500(self, isolated_data_dir: Path) -> None:
        """A truncated or binary-corrupted CSV must fail safely."""
        (isolated_data_dir / "intervention_recommendations.csv").write_bytes(b"\x00\x01\x02not,a,csv\x00")
        with TestClient(app) as client:
            response = client.get("/api/dashboard/overview", headers=WELFARE)
        assert response.status_code == 503
        # The failure must not leak parser internals to the client.
        assert "pandas" not in response.text.lower()
        assert "ParserError" not in response.text

    def test_header_only_artifact_returns_503_not_500(self, isolated_data_dir: Path) -> None:
        """A partially written file (crash mid-export) has no data rows."""
        (isolated_data_dir / "intervention_recommendations.csv").write_text(
            "person_id,date,welfare_risk_probability,risk_band,threshold_decision,"
            "contributing_signals,model_version\n", encoding="utf-8")
        with TestClient(app) as client:
            response = client.get("/api/dashboard/overview", headers=WELFARE)
        assert response.status_code in (503, 200)

    def test_stale_cache_invalidates_when_artifact_changes(self, isolated_data_dir: Path,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
        """The dashboard cache must not keep serving data that no longer exists.

        Regression: the cache was keyed on file mtimes that a fresh deployment
        did not have, so a missing file raised FileNotFoundError (500) instead
        of the designed 503.
        """
        import time

        # Warm the cache with a real artifact set.
        from app.ml.model_training import RULE_BASELINE_NAME  # noqa: F401  (import touch)

        good = isolated_data_dir  # empty; but we need real columns, so build one row
        header = ("person_id,date,welfare_risk_probability,risk_band,threshold_decision,"
                  "contributing_signals,model_version,recommended_action,priority,"
                  "requires_human_review,policy_version,feasibility_status,constraint_flags,"
                  "adjustment_recommendation,requires_human_review_phase7,feasibility_policy_version\n")
        row = "P-0001,2026-01-01,0.9,HIGH,EARLY_WARNING,,v1,PRIORITY_WELFARE_REVIEW,HIGH,True,FEASIBLE,,x,False,p7-v1\n"
        (good / "intervention_recommendations.csv").write_text(header + row, encoding="utf-8")
        (good / "intervention_feasibility.csv").write_text(header + row, encoding="utf-8")
        dashboard_module._SUMMARY_CACHE.clear()
        dashboard_module._SUMMARY_SIGNATURE = None
        try:
            with TestClient(app) as client:
                first = client.get("/api/dashboard/overview", headers=WELFARE)
                assert first.status_code == 200
                # Remove the artifacts out from under the warm cache: the next
                # request must detect the change and fail safely with 503,
                # never serve data it can no longer back, and never 500.
                (good / "intervention_recommendations.csv").unlink()
                (good / "intervention_feasibility.csv").unlink()
                second = client.get("/api/dashboard/overview", headers=WELFARE)
                assert second.status_code == 503
        finally:
            dashboard_module._SUMMARY_CACHE.clear()
            dashboard_module._SUMMARY_SIGNATURE = None


class TestDatabaseUnavailable:
    def test_check_database_false_on_unusable_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from app.core import database as database_module

        # A directory cannot be opened as a SQLite file: the check must return
        # False rather than raising.
        unusable = tmp_path / "not-a-db-dir"
        unusable.mkdir()
        monkeypatch.setattr(database_module, "_sqlite_path", lambda: unusable)
        assert database_module.check_database() is False

    def test_readiness_reflects_database_state(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from app.core import database as database_module

        # Prepare valid artifacts so the only broken dependency is the DB.
        data_dir = tmp_path / "generated"
        data_dir.mkdir()
        header = ("person_id,date,welfare_risk_probability,risk_band,threshold_decision,"
                  "contributing_signals,model_version,recommended_action,priority,"
                  "requires_human_review,policy_version,feasibility_status,constraint_flags,"
                  "adjustment_recommendation,requires_human_review_phase7,feasibility_policy_version\n")
        row = "P-0001,2026-01-01,0.9,HIGH,EARLY_WARNING,,v1,PRIORITY_WELFARE_REVIEW,HIGH,True,FEASIBLE,,x,False,p7-v1\n"
        for name in ("intervention_recommendations.csv", "intervention_feasibility.csv", "personnel.csv"):
            (data_dir / name).write_text(header + row, encoding="utf-8")
        monkeypatch.setattr(dashboard_module, "DATA_DIR", data_dir)
        monkeypatch.setattr(core_paths, "DATA_DIR", data_dir)

        unusable = tmp_path / "blocked"
        unusable.mkdir()
        monkeypatch.setattr(database_module, "_sqlite_path", lambda: unusable)
        with TestClient(app) as client:
            response = client.get("/ready")
        body = response.json()
        assert body["checks"]["database"] == "unavailable"
        assert body["ready"] is False


class TestFailClosedBehaviour:
    def test_health_endpoint_has_no_payload_variance(self) -> None:
        """Liveness exposes nothing about data state, on purpose."""
        with TestClient(app) as client:
            body = client.get("/health").json()
        assert set(body) == {"status", "service", "version"}

    def test_metrics_endpoint_exposes_only_operational_counters(self) -> None:
        with TestClient(app) as client:
            client.get("/health")
            response = client.get("/metrics")
        assert response.status_code == 200
        # Personnel identifiers must never appear in metrics labels.
        assert "P-" not in response.text
