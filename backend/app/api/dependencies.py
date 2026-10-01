"""Single authorization choke point for the FORTIFY API.

Every route resolves its caller through :func:`require_principal` and then
states, in one place, which *view class* it belongs to. Previously each router
had its own copy of header parsing and role checks, and three endpoints checked
membership in the role/purpose matrix without ever checking that the purpose
matched the sensitivity of the data being returned - which is how an auditor
with ``AUDIT`` purpose could enumerate per-person risk scores.

Authorization is expressed as a small vocabulary rather than ad-hoc role string
comparisons, so adding a role or purpose is a single change in
``security_config`` plus the relevant map here.

Data sensitivity classes:

``aggregate``
    Counts and unit-level aggregates only. No personnel identifiers.
    Requires ``AGGREGATE_OPERATIONS``.
``welfare``
    Individual person-level welfare detail. Requires ``WELFARE_SUPPORT``.
``audit``
    Governance metadata. Requires ``AUDIT``.
``infrastructure``
    Service health and configuration. Requires ``INFRASTRUCTURE_ADMIN``.
"""
from __future__ import annotations

import logging
from typing import Iterable

from fastapi import Header, HTTPException

from app.security.audit import AuditEvent, AuditLog
from app.security.principal import AuthenticationError, Authenticator, HeaderTrustAuthenticator, Principal
from app.security.security_config import AccessPurpose, SecurityRole

_AUTHENTICATOR: Authenticator = HeaderTrustAuthenticator()

# Which purpose each view class demands.
VIEW_PURPOSE: dict[str, AccessPurpose] = {
    "aggregate": AccessPurpose.AGGREGATE_OPERATIONS,
    "welfare": AccessPurpose.WELFARE_SUPPORT,
    "audit": AccessPurpose.AUDIT,
    "infrastructure": AccessPurpose.INFRASTRUCTURE_ADMIN,
}

# Roles permitted to use each view class, independent of purpose membership.
VIEW_ROLES: dict[str, frozenset[str]] = {
    "aggregate": frozenset({SecurityRole.WELFARE_OFFICER.value, SecurityRole.COMMANDER.value}),
    "welfare": frozenset({SecurityRole.WELFARE_OFFICER.value}),
    "audit": frozenset({SecurityRole.AUDITOR.value}),
    "infrastructure": frozenset({SecurityRole.SYSTEM_ADMINISTRATOR.value}),
}


def get_authenticator() -> Authenticator:
    return _AUTHENTICATOR


def set_authenticator(authenticator: Authenticator) -> None:
    """Install a real authenticator (OIDC/OAuth2) in place of header trust."""
    global _AUTHENTICATOR
    _AUTHENTICATOR = authenticator


def require_principal(
    x_fortify_role: str | None = Header(default=None),
    x_fortify_purpose: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> Principal:
    """Resolve the caller. The only place credentials are interpreted."""
    credentials = {"role": x_fortify_role or "", "purpose": x_fortify_purpose or ""}
    if authorization:
        # Reserved for a bearer-token authenticator; header trust ignores it.
        credentials["authorization"] = authorization
    try:
        return _AUTHENTICATOR.authenticate(credentials)
    except AuthenticationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.reason) from exc


def authorize_view(
    principal: Principal,
    view: str,
    resource: str,
    audit_path=None,
    *,
    extra: Iterable[str] = (),
) -> None:
    """Enforce that ``principal`` may read/write a view class, and audit it.

    Audits exactly one ALLOWED/DENIED record per decision, from the layer that
    makes the final call. Previously a denial produced both an ALLOWED and a
    DENIED record, because the route audited the coarse matrix decision while
    the service layer audited the finer-grained one.
    """
    required_purpose = VIEW_PURPOSE.get(view)
    allowed_roles = VIEW_ROLES.get(view)
    if required_purpose is None or allowed_roles is None:
        raise HTTPException(status_code=500, detail="Unknown authorization view")

    reason: str | None = None
    if principal.purpose != required_purpose:
        reason = f"This view requires the {required_purpose.value} access purpose."
    elif principal.role.value not in allowed_roles:
        reason = f"This view is restricted to {sorted(allowed_roles)}."

    if audit_path is not None:
        _record_access_decision(principal, view, required_purpose, resource, reason, extra, audit_path)

    if reason:
        # Uniform message: never disclose whether the underlying object exists.
        raise HTTPException(status_code=403, detail=reason)


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _record_access_decision(
    principal: Principal,
    view: str,
    required_purpose: AccessPurpose,
    resource: str,
    reason: str | None,
    extra: Iterable[str],
    audit_path,
) -> None:
    """Write the access decision to the audit log.

    An authorization decision must be enforced from policy, not from whether
    the audit log happened to be writable. If the log is damaged or
    unwritable, the decision still stands and the failure is surfaced through
    metrics and a warning - never by raising into the request path, which would
    turn a logging fault into an availability incident.
    """
    from app.observability import METRICS

    try:
        AuditLog(audit_path).append(AuditEvent(
            event_type="ACCESS_CONTROL",
            actor_role=principal.role.value,
            purpose=principal.purpose.value,
            outcome="DENIED" if reason else "ALLOWED",
            resource=resource,
            timestamp=_utc_now(),
            details={
                "view": view,
                "required_purpose": required_purpose.value,
                "auth_method": principal.auth_method,
                "authenticated": principal.authenticated,
                **({"reason": reason} if reason else {}),
                **({"context": sorted(extra)} if extra else {}),
            },
        ))
    except Exception:  # noqa: BLE001 - deliberate: never fail a request on a log write
        METRICS.increment("audit_write_failures_total")
        logging.getLogger("fortify").warning(
            "audit_write_failed", extra={"view": view, "outcome": "DENIED" if reason else "ALLOWED"}
        )


def require_aggregate(principal: Principal, resource: str, audit_path=None) -> None:
    authorize_view(principal, "aggregate", resource, audit_path)


def require_welfare(principal: Principal, resource: str, audit_path=None) -> None:
    authorize_view(principal, "welfare", resource, audit_path)


def require_audit(principal: Principal, resource: str, audit_path=None) -> None:
    authorize_view(principal, "audit", resource, audit_path)


def require_infrastructure(principal: Principal, resource: str, audit_path=None) -> None:
    authorize_view(principal, "infrastructure", resource, audit_path)


def principal_from_role_purpose(role: str, purpose: str, audit_path=None, resource: str = "service") -> Principal:
    """Build a Principal for service-layer callers that hold role/purpose directly.

    The workflow service is called both from the API and directly by scripts and
    tests. This keeps that path explicit instead of letting raw strings drift
    into authorization decisions.
    """
    try:
        resolved = Principal(
            subject=f"asserted:{role}",
            role=SecurityRole(role),
            purpose=AccessPurpose(purpose),
            auth_method="header_trust",
            authenticated=False,
        )
    except ValueError as exc:
        raise PermissionError("Unrecognized role or purpose for workflow access.") from exc
    if not resolved.may(resolved.purpose):
        raise PermissionError("Role is not permitted for the requested purpose.")
    return resolved