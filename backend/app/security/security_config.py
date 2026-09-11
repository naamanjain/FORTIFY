from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SecurityRole(str, Enum):
    WELFARE_OFFICER = "WELFARE_OFFICER"
    COMMANDER = "COMMANDER"
    SYSTEM_ADMINISTRATOR = "SYSTEM_ADMINISTRATOR"
    AUDITOR = "AUDITOR"


class AccessPurpose(str, Enum):
    WELFARE_SUPPORT = "WELFARE_SUPPORT"
    AGGREGATE_OPERATIONS = "AGGREGATE_OPERATIONS"
    AUDIT = "AUDIT"
    INFRASTRUCTURE_ADMIN = "INFRASTRUCTURE_ADMIN"


@dataclass(frozen=True)
class SecurityPolicyConfig:
    security_policy_version: str = "phase8-v1"
    token_prefix: str = "ptok_"
    minimum_token_secret_length: int = 32
    audit_algorithm: str = "SHA-256 hash chain"
    prototype_trusted_boundary: str = "FORTIFY application-process trust boundary"


ROLE_PURPOSES = {
    SecurityRole.WELFARE_OFFICER: {
        AccessPurpose.WELFARE_SUPPORT,
        AccessPurpose.AGGREGATE_OPERATIONS,
    },
    SecurityRole.COMMANDER: {AccessPurpose.AGGREGATE_OPERATIONS},
    SecurityRole.SYSTEM_ADMINISTRATOR: {AccessPurpose.INFRASTRUCTURE_ADMIN},
    SecurityRole.AUDITOR: {AccessPurpose.AUDIT},
}
