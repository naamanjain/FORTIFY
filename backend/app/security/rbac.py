from __future__ import annotations

from dataclasses import dataclass, field

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


# ---------------------------------------------------------------------------
# Object-level (unit) scope
# ---------------------------------------------------------------------------
# An explicit, named, demonstration-only permission that reads every unit. It
# exists so the prototype can be exercised without an identity provider, and it
# is honoured ONLY for unauthenticated header-trust principals. A verified
# identity never receives it from configuration.
DEMO_ALL_UNITS = "demo:all-units"


@dataclass(frozen=True)
class UnitScope:
    """The set of units a principal may touch at person level.

    ``all_units`` is never implied by an empty ``units``: absence of scope means
    absence of access, so a token with no unit claim, or a mis-set demo variable,
    reads nothing rather than everything.
    """

    units: frozenset[str] = frozenset()
    all_units: bool = False
    source: str = "none"

    def allows(self, unit_id: str | None) -> bool:
        if unit_id is None or str(unit_id).strip() == "":
            return False
        return self.all_units or str(unit_id) in self.units

    def describe(self) -> dict[str, object]:
        return {
            "scope_source": self.source,
            "scope_all_units": self.all_units,
            "scope_units": sorted(self.units) if not self.all_units else [],
        }

    @classmethod
    def deny_all(cls) -> "UnitScope":
        return cls(source="denied")

    @classmethod
    def script(cls) -> "UnitScope":
        """Scope for non-HTTP callers (pipeline scripts, migrations).

        Only internal code may ask for it; no request path can produce it.
        """
        return cls(all_units=True, source="script")


def resolve_unit_scope(
    *,
    authenticated: bool,
    claim_scope: frozenset[str] | None,
    auth_mode: str,
    demo_scope_value: str,
) -> UnitScope:
    """Single place where identity trust and configuration become a scope.

    A verified identity is scoped strictly by its own claims. An unauthenticated
    header-trust principal is scoped by ``FORTIFY_DEMO_UNIT_SCOPE`` - a list of
    real unit ids, or the sentinel that explicitly grants every unit for the
    demonstration. Anything else fails closed.
    """
    if authenticated:
        if not claim_scope:
            return UnitScope(source="claims-empty")
        return UnitScope(units=frozenset(claim_scope), source="claims")

    if auth_mode != "demo":
        # Header trust is not available outside demo mode; refuse rather than
        # fall through to a permissive branch.
        return UnitScope(source="mode-refused")

    raw = (demo_scope_value or "").strip()
    if not raw:
        return UnitScope(source="demo-unconfigured")
    if raw == DEMO_ALL_UNITS:
        return UnitScope(all_units=True, source="demo-all")
    parts = [item.strip() for item in raw.split(",")]
    if any(not item for item in parts) or any(item == DEMO_ALL_UNITS for item in parts):
        # Malformed, or the demo sentinel smuggled into a unit list.
        return UnitScope(source="demo-malformed")
    return UnitScope(units=frozenset(parts), source="demo-list")
