"""OIDC bearer-token validation tests.

These tests exercise OUR validator (app.security.oidc) against locally
generated RSA keys. This is not a fake identity provider: no login, session,
or user-issuing behaviour is implemented or implied. The IdP side of the
contract is documented in docs/OIDC_INTEGRATION.md and remains a departmental
responsibility.
"""
from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.main import app
from app.security.oidc import OIDCAuthenticator, OIDCConfig
from app.security.principal import AuthenticationError

NOW = int(time.time())
KID = "test-key-1"


def _generate_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def rsa_key():
    return _generate_key()


@pytest.fixture(scope="module")
def config():
    return OIDCConfig(
        issuer="https://idp.department.example",
        audience="fortify-api",
        jwks_uri="https://idp.department.example/.well-known/jwks.json",
    )


class _StubSigningKey:
    def __init__(self, key) -> None:
        self.key = key


class _StubJWKSClient:
    """Returns the locally generated public key, mimicking JWKS lookup."""

    def __init__(self, key) -> None:
        self._key = key

    def get_signing_key_from_jwt(self, token: str) -> _StubSigningKey:
        return _StubSigningKey(self._key.public_key())


def _token(rsa_key, *, roles=("WELFARE_OFFICER",), purpose="WELFARE_SUPPORT",
           issuer="https://idp.department.example", audience="fortify-api",
           subject="officer-123", exp_delta=600, extra=None) -> str:
    payload = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "exp": NOW + exp_delta,
        "iat": NOW,
        "roles": list(roles),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, rsa_key, algorithm="RS256", headers={"kid": KID})


def _authenticator(rsa_key, config) -> OIDCAuthenticator:
    return OIDCAuthenticator(config, jwks_client=_StubJWKSClient(rsa_key))


def test_valid_token_authenticates_with_verified_claims(rsa_key, config) -> None:
    authenticator = _authenticator(rsa_key, config)
    principal = authenticator.authenticate({
        "authorization": f"Bearer {_token(rsa_key)}",
        "purpose": "WELFARE_SUPPORT",
    })
    assert principal.authenticated is True
    assert principal.auth_method == "oidc"
    assert principal.subject == "officer-123"
    assert principal.role.value == "WELFARE_OFFICER"


def test_expired_token_is_rejected(rsa_key, config) -> None:
    authenticator = _authenticator(rsa_key, config)
    with pytest.raises(AuthenticationError, match="expired"):
        authenticator.authenticate({
            "authorization": f"Bearer {_token(rsa_key, exp_delta=-60)}",
            "purpose": "WELFARE_SUPPORT",
        })


def test_wrong_audience_is_rejected(rsa_key, config) -> None:
    authenticator = _authenticator(rsa_key, config)
    with pytest.raises(AuthenticationError):
        authenticator.authenticate({
            "authorization": f"Bearer {_token(rsa_key, audience='other-service')}",
            "purpose": "WELFARE_SUPPORT",
        })


def test_wrong_issuer_is_rejected(rsa_key, config) -> None:
    authenticator = _authenticator(rsa_key, config)
    with pytest.raises(AuthenticationError):
        authenticator.authenticate({
            "authorization": f"Bearer {_token(rsa_key, issuer='https://evil.example')}",
            "purpose": "WELFARE_SUPPORT",
        })


def test_token_without_recognized_role_is_rejected(rsa_key, config) -> None:
    """A valid token with no FORTIFY role must not become an unprivileged
    identity; it is refused."""
    authenticator = _authenticator(rsa_key, config)
    with pytest.raises(AuthenticationError, match="role"):
        authenticator.authenticate({
            "authorization": f"Bearer {_token(rsa_key, roles=('HR_CLERK',))}",
            "purpose": "WELFARE_SUPPORT",
        })


def test_purpose_outside_role_matrix_is_rejected(rsa_key, config) -> None:
    authenticator = _authenticator(rsa_key, config)
    with pytest.raises(AuthenticationError, match="purpose"):
        authenticator.authenticate({
            "authorization": f"Bearer {_token(rsa_key, roles=('WELFARE_OFFICER',))}",
            "purpose": "INFRASTRUCTURE_ADMIN",
        })


def test_tampered_token_is_rejected(rsa_key, config) -> None:
    authenticator = _authenticator(rsa_key, config)
    token = _token(rsa_key)
    forged = token[:-6] + ("AAAAAA" if not token.endswith("AAAAAA") else "BBBBBB")
    with pytest.raises(AuthenticationError):
        authenticator.authenticate({"authorization": f"Bearer {forged}", "purpose": "WELFARE_SUPPORT"})


def test_other_key_signature_is_rejected(rsa_key, config) -> None:
    """Signed by a different key: signature verification must fail."""
    other_key = _generate_key()
    authenticator = _authenticator(rsa_key, config)
    with pytest.raises(AuthenticationError):
        authenticator.authenticate({
            "authorization": f"Bearer {_token(other_key)}",
            "purpose": "WELFARE_SUPPORT",
        })


def test_missing_bearer_header_is_rejected(rsa_key, config) -> None:
    authenticator = _authenticator(rsa_key, config)
    with pytest.raises(AuthenticationError):
        authenticator.authenticate({"purpose": "WELFARE_SUPPORT"})


def test_unit_scope_claim_populates_principal(rsa_key, config) -> None:
    config_with_units = OIDCConfig(
        issuer=config.issuer, audience=config.audience, jwks_uri=config.jwks_uri,
        unit_claim="fortify_units",
    )
    authenticator = _authenticator(rsa_key, config_with_units)
    principal = authenticator.authenticate({
        "authorization": f"Bearer {_token(rsa_key, extra={'fortify_units': ['U-001', 'U-002']})}",
        "purpose": "WELFARE_SUPPORT",
    })
    assert principal.unit_scope == frozenset({"U-001", "U-002"})


def test_production_mode_with_oidc_env_boots_and_serves(rsa_key, monkeypatch, config) -> None:
    """End-to-end: production mode + OIDC env serves a verified request and
    refuses an unauthenticated one. The JWKS client is stubbed at the
    authenticator level (the IdP itself remains external)."""
    import app.api.dependencies as deps

    monkeypatch.setenv("FORTIFY_AUTH_MODE", "production")
    monkeypatch.setenv("FORTIFY_OIDC_ISSUER", config.issuer)
    monkeypatch.setenv("FORTIFY_OIDC_AUDIENCE", config.audience)
    monkeypatch.setenv("FORTIFY_OIDC_JWKS_URI", config.jwks_uri)

    original = deps.get_authenticator()
    # A verified identity is scoped by its claims, so this end-to-end test now
    # asks for a token that carries the department's unit claim.
    import dataclasses
    from app.services.workflow import _personnel_unit_map
    scoped_config = dataclasses.replace(config, unit_claim="fortify_units")
    p0001_unit = _personnel_unit_map()["P-0001"]
    try:
        deps.set_authenticator(_authenticator(rsa_key, scoped_config))
        with TestClient(app) as client:
            ok = client.get(
                "/api/dashboard/person/P-0001",
                headers={
                    "Authorization": f"Bearer {_token(rsa_key, extra={'fortify_units': [p0001_unit]})}",
                    "X-Fortify-Purpose": "WELFARE_SUPPORT",
                },
            )
            # Same valid token, no unit claim: authenticated for identity, denied
            # for person-level welfare data. Fail closed, not fail open.
            no_claim = client.get(
                "/api/dashboard/person/P-0001",
                headers={
                    "Authorization": f"Bearer {_token(rsa_key)}",
                    "X-Fortify-Purpose": "WELFARE_SUPPORT",
                },
            )
            denied = client.get("/api/dashboard/person/P-0001", headers={"X-Fortify-Purpose": "WELFARE_SUPPORT"})
            wrong_purpose = client.get(
                "/api/dashboard/person/P-0001",
                headers={"Authorization": f"Bearer {_token(rsa_key, roles=('COMMANDER',))}",
                         "X-Fortify-Purpose": "WELFARE_SUPPORT"},
            )
    finally:
        deps.set_authenticator(original)

    assert ok.status_code == 200
    assert no_claim.status_code == 404
    assert denied.status_code == 401
    # A commander token cannot declare welfare purpose: refused before any
    # data access.
    assert wrong_purpose.status_code == 401


def test_production_mode_without_oidc_env_still_fails_closed() -> None:
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    code = (
        "import sys, os; sys.path.insert(0, 'backend'); "
        "os.environ['FORTIFY_AUTH_MODE'] = 'production'; "
        "import app.api.dependencies; print('BOOTED-BAD')"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=root)
    assert "BOOTED-BAD" not in result.stdout
    assert "FORTIFY_OIDC_ISSUER" in result.stderr
