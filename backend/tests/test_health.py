from fastapi.testclient import TestClient

from app.main import APP_VERSION, app


client = TestClient(app)


def test_health_is_liveness_only_and_reports_version() -> None:
    """Liveness must not depend on the database or on generated data.

    If it did, a deployment missing its dataset would be restarted forever
    instead of reporting a useful readiness failure.
    """
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "FORTIFY"
    assert body["version"] == APP_VERSION


def test_readiness_reports_dependency_state() -> None:
    response = client.get("/ready")
    body = response.json()
    assert response.status_code in (200, 503)
    # Whatever the outcome, the decision and its causes must be explained.
    assert body["ready"] is (response.status_code == 200)
    assert body["version"] == APP_VERSION
    assert set(body["checks"]) == {"database", "artifacts", "data_quality"}
    if not body["ready"]:
        assert body["remedy"]


def test_version_endpoint_matches_health() -> None:
    health = client.get("/health").json()
    version = client.get("/version").json()
    assert version["version"] == health["version"]
    assert version["service"] == "FORTIFY"