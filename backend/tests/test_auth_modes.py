"""Authentication-mode tests.

The demo authenticator is honest about being unauthenticated, and production
mode must fail closed at startup rather than serve requests on header trust.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[2]


def test_demo_mode_reports_unauthenticated_principal() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/dashboard/system-health",
            headers={"X-Fortify-Role": "AUDITOR", "X-Fortify-Purpose": "AUDIT"},
        )
    assert response.status_code == 200
    governance = response.json()["governance"]
    assert governance["authenticated"] is False
    assert governance["auth_method"] == "header_trust"


def test_production_mode_fails_closed_at_startup() -> None:
    """FORTIFY_AUTH_MODE=production without a real IdP must refuse to boot.

    Verified in a fresh interpreter so the module-level authenticator
    resolution actually runs with the production setting.
    """
    code = (
        "import sys, os; sys.path.insert(0, 'backend'); "
        "os.environ['FORTIFY_AUTH_MODE'] = 'production'; "
        "import app.api.dependencies; print('BOOTED-BAD')"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert "BOOTED-BAD" not in result.stdout, "production mode booted on header trust"
    assert "FORTIFY_AUTH_MODE=production requires" in result.stderr


def test_unknown_auth_mode_fails_closed() -> None:
    code = (
        "import sys, os; sys.path.insert(0, 'backend'); "
        "os.environ['FORTIFY_AUTH_MODE'] = 'kerberos'; "
        "import app.api.dependencies; print('BOOTED-BAD')"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert "BOOTED-BAD" not in result.stdout
    assert "Unknown FORTIFY_AUTH_MODE" in result.stderr


def test_production_authenticator_can_be_registered() -> None:
    """The seam works: a real authenticator replaces header trust at runtime.

    This is the integration point an OIDC implementation would use - proven
    here with a test double that issues authenticated principals, not with a
    fake identity provider pretending to be production.
    """
    import app.api.dependencies as deps
    from app.security.principal import AuthenticationError, Principal
    from app.security.security_config import AccessPurpose, SecurityRole

    class StubOIDC:
        method_name = "oidc"

        def authenticate(self, credentials: dict[str, str]) -> Principal:
            token = credentials.get("authorization", "")
            if not token.startswith("Bearer "):
                raise AuthenticationError("Bearer token required.")
            return Principal(
                subject="user-from-token",
                role=SecurityRole.WELFARE_OFFICER,
                purpose=AccessPurpose.WELFARE_SUPPORT,
                auth_method=self.method_name,
                authenticated=True,
            )

    original = deps.get_authenticator()
    try:
        deps.set_authenticator(StubOIDC())
        with TestClient(app) as client:
            ok = client.get(
                "/api/dashboard/person/P-0001",
                headers={"Authorization": "Bearer test-token"},
            )
            denied = client.get("/api/dashboard/person/P-0001")
        assert ok.status_code == 200
        assert denied.status_code == 401
    finally:
        deps.set_authenticator(original)
