"""Authentication boundary for FORTIFY.

Authentication ("who is calling?") and authorization ("may they do this?") are
kept deliberately separate:

* This module turns *credentials* into a :class:`Principal`. It is the only
  place that knows how a caller is identified.
* ``app.security.rbac`` decides what a :class:`Principal` may do. It never sees
  a header, a token, or a socket.

The prototype ships :class:`HeaderTrustAuthenticator`, which trusts two
attacker-controllable request headers. That is **not authentication** - it is a
deliberate placeholder so the demonstration environment has no identity
provider to stand up. It is named and reported as such everywhere it surfaces
in an API response.

To move to a real deployment, implement :class:`Authenticator` against an
OIDC/OAuth2 provider, register it in ``app.security.auth.build_authenticator``,
and nothing in the authorization layer needs to change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .security_config import AccessPurpose, ROLE_PURPOSES, SecurityRole


@dataclass(frozen=True)
class Principal:
    """An authenticated (or, in the prototype, merely asserted) caller.

    ``authenticated`` is False for header trust. Code that needs to distinguish
    a real identity from an asserted one - such as the governance endpoints -
    can check it instead of assuming.
    """

    subject: str
    role: SecurityRole
    purpose: AccessPurpose
    auth_method: str
    authenticated: bool = False
    unit_scope: frozenset[str] = field(default_factory=frozenset)

    def may(self, purpose: AccessPurpose | str) -> bool:
        """Whether this principal's role grants the given purpose at all."""
        try:
            target = AccessPurpose(purpose)
        except ValueError:
            return False
        return target in ROLE_PURPOSES.get(self.role, set())

    def describe(self) -> dict[str, object]:
        """Non-sensitive description safe to return in a response."""
        return {
            "subject": self.subject,
            "role": self.role.value,
            "purpose": self.purpose.value,
            "auth_method": self.auth_method,
            "authenticated": self.authenticated,
        }


class AuthenticationError(Exception):
    """Credentials were absent or could not be interpreted."""

    def __init__(self, reason: str, status_code: int = 401) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


class Authenticator(Protocol):
    """The seam a real identity provider plugs into."""

    method_name: str

    def authenticate(self, credentials: dict[str, str]) -> Principal:
        """Resolve credentials to a Principal, or raise AuthenticationError."""
        ...


class HeaderTrustAuthenticator:
    """Prototype authenticator: trusts ``X-Fortify-Role`` / ``X-Fortify-Purpose``.

    This performs **no verification whatsoever**. The headers are supplied by
    the caller and are indistinguishable from attacker input. It exists so the
    demonstration environment can exercise the authorization model without an
    identity provider, and every Principal it issues has ``authenticated=False``
    so nothing downstream can mistake it for a real session.

    Replace it with an OIDC implementation; do not extend it.
    """

    method_name = "header_trust"

    def __init__(self, *, require_flag: str | None = "FORTIFY_ALLOW_HEADER_AUTH") -> None:
        self.require_flag = require_flag

    def authenticate(self, credentials: dict[str, str]) -> Principal:
        role_raw = (credentials.get("role") or "").strip()
        purpose_raw = (credentials.get("purpose") or "").strip()
        if not role_raw or not purpose_raw:
            raise AuthenticationError(
                "This deployment requires authenticated credentials. "
                "The prototype header-trust mechanism is disabled."
            )
        try:
            role = SecurityRole(role_raw)
            purpose = AccessPurpose(purpose_raw)
        except ValueError as exc:
            # Do not echo the offending value back; it is attacker-controlled.
            raise AuthenticationError("Credentials are not recognized.") from exc
        return Principal(
            subject=f"asserted:{role_raw}",
            role=role,
            purpose=purpose,
            auth_method=self.method_name,
            authenticated=False,
        )