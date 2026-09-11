# Security Model

## Principles
Privacy is an architectural requirement. Personnel identity should not unnecessarily travel through analytics components. Analytics should use tokenized/pseudonymous identifiers.

## Production security architecture
Eventually support:
1. identity/data separation
2. tokenized personnel identifiers
3. encryption at rest
4. encryption in transit
5. role-based access control
6. purpose-bound access
7. audit logging
8. separation from disciplinary/performance systems
9. trusted computation architecture
10. remote attestation architecture

## Roles
- Welfare Officer: authorized welfare cases, trajectories, explanations, simulations, outcomes.
- Commander / Authorized Leadership: primarily aggregate operational welfare trends; individual access only under authorization policy.
- System Administrator: infrastructure management without automatic unrestricted welfare access.
- Auditor: audit records.

## Trusted execution
Potential production technologies include Intel TDX, AMD SEV-SNP, confidential VMs, hardware-backed trusted execution, remote attestation, and hardware-backed key release.

## Prototype boundary
The Phase 0 prototype does **not** claim hardware-backed confidential computing. The intended boundary is:

`PROTECTED DATA → TRUSTED COMPUTATION BOUNDARY → ANALYTICS / INFERENCE → AUTHORIZED RESULT → AUDIT`

Prototype security implementation and production security architecture must remain clearly distinguished.

## Phase 5 privacy/safety controls
The Phase 5 decision output is deliberately narrower than the underlying model-data table. It contains no raw mood, energy, sleep-quality, perceived-stress, workload-manageability, or support-request values.

Risk bands are operational/welfare monitoring signals only and must not be used as disciplinary or performance scores. Explanations identify contributing operational signals without claiming causality or diagnosing an individual's mental or medical state.

Calibration and threshold selection use held-out validation labels only; test labels are reserved for final evaluation. The Phase 5 model card documents the synthetic-data limitation, sparse self-report target, excluded/unusable evaluation rows, and the need for human welfare-professional review before operational use.



## Phase 6 safety boundary
Phase 6 produces welfare-support recommendations for human review only. It does not execute interventions or communicate with personnel. Output excludes raw voluntary wellness responses and contains only operational signals, risk-band context, recommendation metadata, and human-review flags.

Policy safeguards prohibit medical/psychiatric conclusions, disciplinary or punitive actions, performance scoring, termination recommendations, and automatic adverse personnel actions. Recommendations are probabilistic support signals and must not be treated as statements about an individual's mental state.

Phase 7 will be responsible for explicit operational feasibility/constraint handling; Phase 6 does not optimize staffing or workforce allocation.

## Phase 7 safety/privacy boundary
Phase 7 outputs use operational constraints only and do not expose raw voluntary wellness responses. It cannot produce medical diagnoses, disciplinary actions, performance ratings, punishment, termination, or automatic adverse personnel actions. Constrained implementation is routed to human coordination/review.

## Phase 8 security implementation

### Identity/data separation
Analytics-facing identifiers can be generated with deterministic HMAC-SHA256 pseudonymization. The personnel identifier itself is not required to travel through analytics components. The mapping secret is supplied outside source control.

### Encryption
`backend/app/security/crypto.py` provides authenticated encryption for protected fields/blobs using the existing `cryptography` dependency and a caller-supplied Fernet key. Keys are not hard-coded into the repository. Prototype encryption utilities do not claim storage-provider or database-file encryption by themselves.

### Purpose-bound RBAC
The prototype defines four existing architectural roles and explicit access purposes. Welfare access is limited to the welfare role; commanders receive aggregate operational purpose access; infrastructure administration does not automatically grant welfare access; auditors receive audit-purpose access.

### Audit logging
`AuditLog` writes append-only JSONL events with a SHA-256 hash chain. Verification detects tampering or chain breaks. Audit details should contain operational metadata rather than raw voluntary wellness responses.

### Trusted computation boundary
The prototype exposes an explicit boundary object requiring protected input before analytics/inference execution. `hardware_tee=False` is intentional. Production architecture may later bind this boundary to confidential-computing hardware, remote attestation, and hardware-backed key release.

### Prototype versus production
Phase 8 implements application-level controls and a clearly defined trust boundary. It does not claim production confidential computing, HSM-backed secrets, hardware attestation, or a complete identity-management system.

### Safety/privacy restrictions
Phase 8 does not add diagnosis, disciplinary scoring, performance scoring, punishment, termination, or automatic adverse personnel actions. Operational outputs remain narrower than underlying data and must not expose raw voluntary wellness responses unnecessarily.

## Phase 9 dashboard use of security primitives

The prototype dashboard consumes Phase 8 purpose-bound authorization before returning aggregate or individual welfare data. Individual personnel detail requires `WELFARE_OFFICER` + `WELFARE_SUPPORT`; commanders are limited to aggregate operational views. Dashboard access is audit-recorded. The request headers are a prototype enforcement boundary and are not equivalent to a production identity provider.

## Phase 10 workflow security
Individual workflow inspection and state changes require the existing purpose-bound `WELFARE_OFFICER` + `WELFARE_SUPPORT` authorization. Audit history is readable by authorized welfare users and `AUDITOR` + `AUDIT`. Workflow storage contains operational recommendation/feasibility metadata only; raw wellness fields are excluded.

Every human transition is mirrored into the Phase 8 append-only hash-chained audit log and includes actor role, purpose, prior/new state, reason code, workflow/policy/model versions, and timestamp. The workflow layer does not create autonomous personnel actions.



## Phase 11 hardening boundary

Phase 11 strengthens the existing prototype security boundary without changing the Phase 8 authorization model. SQLite workflow access enables foreign-key enforcement and a bounded busy timeout; workflow transitions acquire an immediate transaction so concurrent requests cannot both act on the same stale workflow state. The dashboard cache is invalidated when its source artifacts change. The hardening validator verifies the existing hash-chain audit log, workflow integrity, artifact grain, and privacy schema.

These are prototype reliability controls. They are not a substitute for production database migration, centralized identity, HSM-backed secret management, or hardware-backed confidential computing.

## Phase 13 — Governance experience

Phase 13 surfaces the existing Phase 8 security model in the product experience. Individual personnel discovery/detail remains restricted to the welfare-support role/purpose. Command views are aggregate-first. Audit and system-health views are role-bound. Search respects the same distinction and does not return individual identities to aggregate-only callers.

The frontend does not receive raw wellness/self-report values. Security indicators are informative UX surfaces; the existing backend authorization remains authoritative.
