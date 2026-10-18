# OIDC / OAuth2 integration contract

This document is the contract a department identity provider must satisfy for
FORTIFY to run in production mode. The relying-party side (token validation)
is implemented in `backend/app/security/oidc.py` and verified by
`backend/tests/test_oidc.py` against locally generated signing keys. The IdP
side is a departmental responsibility; nothing here implements one.

## Required IdP capabilities

| Capability | Requirement |
|---|---|
| Protocol | OIDC / OAuth2 with JWT access tokens |
| Signing | RS256 (required) or ES256 |
| Key publication | JWKS endpoint with `kid`-keyed keys, cacheable, rotatable |
| Token contents | `iss`, `aud`, `sub`, `exp` **required**; role claim; optional unit-scope claim |

## Environment configuration (all three required in production mode)

| Variable | Meaning | Example |
|---|---|---|
| `FORTIFY_OIDC_ISSUER` | Exact `iss` value to accept | `https://idp.department.example` |
| `FORTIFY_OIDC_AUDIENCE` | Exact `aud` value for FORTIFY API tokens | `fortify-api` |
| `FORTIFY_OIDC_JWKS_URI` | JWKS URL for signature verification | `https://idp.department.example/.well-known/jwks.json` |
| `FORTIFY_OIDC_ROLE_CLAIM` | Claim carrying FORTIFY roles (default `roles`) | `roles` or `groups` |
| `FORTIFY_OIDC_UNIT_CLAIM` | Optional claim listing unit ids for officer scoping | `fortify_units` |
| `FORTIFY_OIDC_LEEWAY_SECONDS` | Clock tolerance for `exp`/`nbf` (default 30) | `30` |
| `FORTIFY_OIDC_JWKS_CACHE_SECONDS` | JWKS refresh window (default 300) | `300` |

## Token validation performed on every request

1. `Authorization: Bearer <token>` header present; otherwise 401.
2. Signature verified against the JWKS key matching the token `kid`.
3. `iss` equals `FORTIFY_OIDC_ISSUER` exactly.
4. `aud` includes `FORTIFY_OIDC_AUDIENCE`.
5. `exp` present and not expired (`nbf` honoured) within `leeway_seconds`.
6. `sub` present and non-empty → principal identity.
7. Role claim contains **at least one** role from the FORTIFY role set below;
   a token with none is refused — there is no default role.
8. The request's declared purpose must be permitted for the verified role
   (purpose/role matrix in `security_config.py`); otherwise refused before any
   data access.

## Required role claims per FORTIFY role

| FORTIFY role | Token role value | Grants |
|---|---|---|
| Welfare Officer | `WELFARE_OFFICER` | Individual welfare review (WELFARE_SUPPORT), aggregate views |
| Command / Leadership | `COMMANDER` | Aggregate operational views only (AGGREGATE_OPERATIONS) |
| Administrator | `SYSTEM_ADMINISTRATOR` | Infrastructure/system health (INFRASTRUCTURE_ADMIN) |
| Auditor | `AUDITOR` | Audit trail and audit health (AUDIT) |
| System Operator | `SYSTEM_ADMINISTRATOR` + operational access to hosts; FORTIFY itself grants only INFRASTRUCTURE_ADMIN — deployment tooling lives outside the application | Infrastructure administration |

The unit-scope claim (`FORTIFY_OIDC_UNIT_CLAIM`) carries unit ids (`U-xxx`) that
narrow an identity's object-level scope, and that scope is now **enforced**:
every person-level read and every case mutation is bound to it, the restriction
is applied in the query before counting, sorting and paging, and it is re-checked
on the locked row inside the mutation transaction. An out-of-scope person or case
answers with the same 404 as an unknown one, so the API cannot be used to
discover which identifiers exist.

Semantics that a department integrating an IdP must understand:

* A verified identity is scoped **only** by its own claims. Empty, missing,
  malformed or unrecognised scope means no person-level access - never "all
  units". A token that authenticates successfully but carries no unit claim is
  authenticated and still denied welfare data.
* The demonstration-wide permission `FORTIFY_DEMO_UNIT_SCOPE=demo:all-units` is
  honoured **only** for unauthenticated header-trust principals, and only while
  `FORTIFY_AUTH_MODE=demo`. It cannot widen a verified identity, and production
  mode still refuses to start without a real authenticator.
* The scope is never read from a request header or query parameter. Setting
  `X-Fortify-Units` (or any similar header) has no effect, by test.
* Command keeps aggregate-only views inside its assigned units; auditors and
  administrators never inherit person-level welfare access, and per-case history
  returned to the `AUDIT` purpose has personnel identifiers removed.

Still **remaining work**: the unit roster itself, and the policy questions the
mechanism cannot answer - multi-unit officers, transfers mid-case, acting
command assignments, and who may grant a wider scope. Those need departmental
policy, not code.

## Key rotation

The IdP publishes new keys in JWKS with a new `kid` and keeps old keys
verifiable during the overlap. FORTIFY refreshes its JWKS cache at
`FORTIFY_OIDC_JWKS_CACHE_SECONDS`; tokens signed by a rotated-in key verify
within one cache window without restart. Publish-then-retire: add the new key,
wait beyond the cache window, then remove the old key.

## Clock tolerance

`exp`/`nbf` are validated with `FORTIFY_OIDC_LEEWAY_SECONDS` (default 30s)
absorbing modest clock skew. The IdP and FORTIFY hosts should run NTP; the
leeway is tolerance, not a design assumption.

## Logout and session expectations

FORTIFY is a stateless resource server: it holds no sessions and stores no
tokens. Logout is therefore the IdP's session termination; after logout,
**unexpired access tokens remain valid until `exp`** unless the IdP exposes
revocation that FORTIFY checks. This implementation does not perform
introspection or revocation lookups (a deliberate, documented limitation);
the mitigation is short token lifetimes:

- **Recommended access-token lifetime: ≤ 10 minutes.**
- Refresh tokens are handled entirely by the frontend/IdP; FORTIFY never sees
  them.

## What this integration deliberately does not include

- No login, consent, MFA, or account lifecycle: IdP responsibilities.
- No introspection/revocation endpoint calls: see logout note above.
- No SCIM/user provisioning: role assignment is IdP-side.
- No fallback authentication path: if OIDC is unconfigured, production mode
  refuses to boot; it never degrades to header trust.
