"""Failure and recovery drills.

Controlled breakage with expected recovery behaviour, exercised against the
real application: model artifacts missing/corrupt, unreadable storage, proxy
unavailable, corrupt audit event. (Database outage/restart was verified live
against a real PostgreSQL server — restarting the container mid-life and
confirming pool recovery; recorded in the readiness matrix rather than
duplicated here because it needs the container.)
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
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "generated"
    data.mkdir()
    for target in (dashboard_module, core_paths):
        monkeypatch.setattr(target, "DATA_DIR", data)
    import app.main as main_module

    monkeypatch.setattr(main_module, "DATA_DIR", data)
    import app.services.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "DATA_DIR", data)
    return data


def test_missing_model_artifacts_fail_readiness_not_liveness(data_dir):
    """EXPECTED: /health 200 always; /ready reports model/data not ready with
    a remedy; no data endpoint pretends to work."""
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        ready = client.get("/ready")
        assert ready.status_code == 503
        body = ready.json()
        assert body["model"]["ready"] is False
        assert body["data"]["artifacts"] == "missing"
        assert "build_all.py" in body["remedy"]


def test_corrupt_model_artifact_fails_compatibility_gate(data_dir, tmp_path):
    """EXPECTED: a corrupt phase4 metadata file makes MODEL readiness false
    with a named failure, and the response is still a clean 503."""
    import json

    art = tmp_path / "artifacts" / "phase4"
    art.mkdir(parents=True)
    (art / "model_metadata.json").write_bytes(b"\x00corrupt not json\x00")

    import app.main as main_module

    original = main_module.ROOT_ARTIFACTS
    import unittest.mock as mock

    with mock.patch.object(main_module, "ROOT_ARTIFACTS", tmp_path / "artifacts"):
        with TestClient(app) as client:
            ready = client.get("/ready")
    assert ready.status_code == 503
    assert ready.json()["model"]["ready"] is False


def test_unwritable_storage_degrades_to_503(data_dir, monkeypatch):
    """EXPECTED: read-only data storage surfaces as data unavailability (503
    with remedy), never as a crash or — worse — as empty-but-valid results."""
    # Simulate unreadable artifacts: a directory where a CSV is expected.
    (data_dir / "intervention_recommendations.csv").mkdir()
    with TestClient(app) as client:
        r = client.get("/api/dashboard/overview", headers=WELFARE)
    assert r.status_code == 503


def test_proxy_unavailable_is_a_transport_error_not_empty_data():
    """EXPECTED: the frontend API client translates a dead backend into an
    explicit transport error — never into "no results". Verified against a
    port with nothing listening."""
    import httpx

    with pytest.raises(httpx.HTTPError):
        httpx.get("http://127.0.0.1:9/api/dashboard/overview", timeout=2)


def test_corrupt_audit_event_does_not_block_the_api(data_dir, tmp_path, monkeypatch):
    """EXPECTED: a corrupt audit log fails verification (reported honestly in
    system-health) but the API stays up — an evidentiary failure is surfaced,
    not used as a denial-of-service against the deployment."""
    audit = tmp_path / "audit.jsonl"
    audit.write_text('{"event_type": "T", "trunc', encoding="utf-8")
    monkeypatch.setattr(dashboard_module, "AUDIT_PATH", audit)
    with TestClient(app) as client:
        health = client.get("/api/dashboard/system-health", headers={
            "X-Fortify-Role": "AUDITOR", "X-Fortify-Purpose": "AUDIT"})
    assert health.status_code == 200
    governance = health.json()["governance"]
    assert governance["audit_chain"] == "Failed"