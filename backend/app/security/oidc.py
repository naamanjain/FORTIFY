"""OIDC / OAuth2 bearer-token authentication for production mode.

This module implements the *relying-party* side of the OpenID Connect
contract: validating bearer tokens issued by the department's identity
provider. It does NOT implement an identity provider, and nothing here should
be mistaken for one - see docs/OIDC_INTEGRATION.md for the full contract a
department IdP must satisfy.

What is verified for every request in production mode:

1. **Signature** against the IdP's published JWKS (RS256/ES256), with key
   rotation handled by kid lookup and PyJWKClient caching.
2. **Issuer** (``iss``) and **audience** (``aud``) exactly match configuration.
3. **Expiry** (``exp``/``nbf``) with a small configurable clock tolerance.
4. **Role claim**: the token must carry at least one FORTIFY role the
   authenticator recognises; a token with no recognised role is rejected
   rather than defaulted to an unprivileged role.
5. **Subject** (``sub``) becomes the principal identity.

Authorization still uses the verified role plus the *declared purpose* of the
request. Purpose remains a request-level declaration on purpose: a bearer
token asserts who you are, not what you are doing on this particular request.
The authorization layer refuses purpose/role combinations the role does not
permit (see ``app.api.dependencies``), so a valid token cannot buy access to
the wrong view class.

Production mode fails closed: if FORTIFY_AUTH_MODE=production and the OIDC
environment is not fully configured, startup refuses (see
``build_authenticator``). There is no fallback to header trust.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import jwt
from jwt import PyJWKClient

from .principal import AuthenticationError, Authenticator, Principal
from .security_config import AccessPurpose, SecurityRole


@dataclass(frozen=True)
class OIDCConfig:
    issuer: str
    audience: str
    jwks_uri: str
    role_claim: str = "roles"
    unit_claim: str | None = None          # optional claim listing unit ids
    leeway_seconds: int = 30               # clock tolerance for exp/nbf
    jwks_cache_seconds: int = 300          # key-rotation refresh window

    @staticmethod
    def from_env(env: dict[str, str] | None = None) -> "OIDCConfig | None":
        env = dict(os.environ if env is None else env)
        issuer = env.get("FORTIFY_OIDC_ISSUER", "").strip()
        audience = env.get("FORTIFY_OIDC_AUDIENCE", "").strip()
        jwks_uri = env.get("FORTIFY_OIDC_JWKS_URI", "").strip()
        if not (issuer and audience and jwks_uri):
            return None
        return OIDCConfig(
            issuer=issuer,
            audience=audience,
            jwks_uri=jwks_uri,
            role_claim=env.get("FORTIFY_OIDC_ROLE_CLAIM", "roles"),
            unit_claim=env.get("FORTIFY_OIDC_UNIT_CLAIM") or None,
            leeway_seconds=int(env.get("FORTIFY_OIDC_LEEWAY_SECONDS", "30")),
            jwks_cache_seconds=int(env.get("FORTIFY_OIDC_JWKS_CACHE_SECONDS", "300")),
        )


class OIDCAuthenticator(Authenticator):
    """Validates OIDC bearer tokens and maps verified claims to a Principal."""

    method_name = "oidc"

    def __init__(self, config: OIDCConfig, *, jwks_client: PyJWKClient | None = None) -> None:
        self.config = config
        self._jwks_client = jwks_client or PyJWKClient(
            config.jwks_uri, cache_jwk_set=True, lifespan=config.jwks_cache_seconds
        )

    def authenticate(self, credentials: dict[str, str]) -> Principal:
        header = (credentials.get("authorization") or "").strip()
        if not header.lower().startswith("bearer "):
            raise AuthenticationError("A Bearer access token is required.")
        token = header.split(" ", 1)[1].strip()

        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256"],
                audience=self.config.audience,
                issuer=self.config.issuer,
                leeway=self.config.leeway_seconds,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("The access token has expired.") from exc
        except jwt.InvalidAudienceError as exc:
            raise AuthenticationError("The token is not issued for this service.") from exc
        except jwt.InvalidIssuerError as exc:
            raise AuthenticationError("The token issuer is not trusted.") from exc
        except jwt.MissingRequiredClaimError as exc:
            raise AuthenticationError("The token is missing required claims.") from exc
        except jwt.InvalidTokenError as exc:
            # Generic refusal for anything else (bad signature, malformed,
            # wrong key type): never echo token content back.
            raise AuthenticationError("The access token could not be verified.") from exc

        subject = str(claims.get("sub", "")).strip()
        if not subject:
            raise AuthenticationError("The token has no subject claim.")

        role = self._resolve_role(claims)
        purpose = self._resolve_purpose(credentials, role)
        unit_scope = self._resolve_units(claims)

        return Principal(
            subject=subject,
            role=role,
            purpose=purpose,
            auth_method=self.method_name,
            authenticated=True,
            unit_scope=unit_scope,
        )

    def _resolve_role(self, claims: dict) -> SecurityRole:
        raw_roles = claims.get(self.config.role_claim) or []
        if isinstance(raw_roles, str):
            raw_roles = [raw_roles]
        for candidate in raw_roles:
            try:
                return SecurityRole(str(candidate))
            except ValueError:
                continue
        # A valid token with no recognised FORTIFY role is not an identity this
        # application can authorize; refuse rather than default.
        raise AuthenticationError("The token does not carry a recognized FORTIFY role.")

    def _resolve_purpose(self, credentials: dict[str, str], role: SecurityRole) -> AccessPurpose:
        """Resolve the request's declared purpose against the verified role.

        The purpose is the caller's declaration of intent for THIS request;
        authorization refuses combinations the role does not permit. A purpose
        outside the role's matrix is rejected here so the principal never
        exists with an impossible role/purpose pair.
        """
        declared = (credentials.get("purpose") or "").strip()
        try:
            purpose = AccessPurpose(declared)
        except ValueError as exc:
            raise AuthenticationError("A valid access purpose is required.") from exc
        from .security_config import ROLE_PURPOSES

        if purpose not in ROLE_PURPOSES.get(role, set()):
            raise AuthenticationError("The declared purpose is not permitted for the token's role.")
        return purpose

    def _resolve_units(self, claims: dict) -> frozenset[str]:
        if not self.config.unit_claim:
            return frozenset()
        units = claims.get(self.config.unit_claim) or []
        if isinstance(units, str):
            units = [units]
        return frozenset(str(u) for u in units)


def build_oidc_authenticator(env: dict[str, str] | None = None) -> OIDCAuthenticator:
    config = OIDCConfig.from_env(env)
    if config is None:
        raise RuntimeError(
            "FORTIFY_AUTH_MODE=production requires FORTIFY_OIDC_ISSUER, "
            "FORTIFY_OIDC_AUDIENCE and FORTIFY_OIDC_JWKS_URI to be configured."
        )
    return OIDCAuthenticator(config)