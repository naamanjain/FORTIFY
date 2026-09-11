from __future__ import annotations

from dataclasses import dataclass

from .security_config import AccessPurpose, ROLE_PURPOSES, SecurityPolicyConfig, SecurityRole


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason: str
    policy_version: str


def authorize(
    role: SecurityRole | str,
    purpose: AccessPurpose | str,
    *,
    config: SecurityPolicyConfig | None = None,
) -> AccessDecision:
    config = config or SecurityPolicyConfig()
    try:
        role_enum = SecurityRole(role)
        purpose_enum = AccessPurpose(purpose)
    except ValueError:
        return AccessDecision(False, "Unknown security role or access purpose", config.security_policy_version)

    allowed_purposes = ROLE_PURPOSES.get(role_enum, set())
    if purpose_enum in allowed_purposes:
        return AccessDecision(True, "Purpose is permitted for the role", config.security_policy_version)
    return AccessDecision(False, "Purpose is not permitted for the role", config.security_policy_version)
