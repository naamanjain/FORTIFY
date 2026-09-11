# TODO — Current Phase Only

## Completed phases
- [x] Phase 0 — Project initialization
- [x] Phase 1 — Synthetic operational world
- [x] Phase 2 — Feature engineering
- [x] Phase 3 — Personal + cohort + operational baselines
- [x] Phase 4 — Predictive Risk Modeling

## Phase 4 limitations / follow-up
- Target availability is sparse because it depends on observed future voluntary wellness.
- Metrics are based on synthetic data and are not clinical validation.
- Production calibration and external validation are not performed in the prototype.

## Explicitly deferred
- Phase 5 — Explainability + uncertainty
- Phase 6 — Intervention simulator **(completed)**
- Phase 7 — Operational constraint engine
- Phase 8 — Privacy + security + TEE architecture
- Phase 9 — Dashboard integration
- Phase 10 — End-to-end demonstration
- Phase 11 — Testing + hardening
- Phase 12 — Final demonstration preparation

## Phase 5 limitations / follow-up
- The current 0.25 threshold is a synthetic-prototype operating point and requires policy review before operational deployment.
- Calibration is internal to the held-out synthetic validation/test design and has no external validation.
- The target is based on sparse voluntary self-report observations; many person-days remain unlabeled for supervised evaluation.
- Explanations are associative operational signals, not causal explanations.

## Deferred after Phase 5
- Phase 6 — Intervention simulator **(completed)**
- Phase 7 — Operational constraint engine **(completed)**
- Phase 8 — Privacy + security + TEE architecture **(completed)**
- Phase 9 — Dashboard integration
- Phase 10 — End-to-end demonstration
- Phase 11 — Testing + hardening
- Phase 12 — Final demonstration preparation



## Phase 6 limitations / follow-up
- Recommendations are deterministic policy outputs and are not autonomous actions.
- Cooldown uses consecutive Phase 5 prediction records as the available history; no external intervention-history system exists yet.
- The intervention policy has no staffing or role-coverage feasibility logic; that belongs to Phase 7.
- Synthetic operational data and model signals require human policy review before any real-world use.

## Deferred after Phase 6
- Phase 7 — Operational constraint engine **(completed)**
- Phase 8 — Privacy + security + TEE architecture **(completed)**
- Phase 9 — Dashboard integration
- Phase 10 — End-to-end demonstration
- Phase 11 — Testing + hardening
- Phase 12 — Final demonstration preparation

## Phase 7 remaining issues
- Thresholds are synthetic prototype policy assumptions and require operational validation before production use.
- Current synthetic datasets do not contain explicit staffing-capacity or coverage fields, so feasibility cannot infer real staffing availability.
- Phase 8 must define the production privacy/security boundary; no TEE or production security implementation is part of Phase 7.

## Phase 8 remaining issues
- Production secret management/HSM integration is not implemented.
- Hardware-backed confidential computing, remote attestation, and hardware-backed key release remain production architecture work.
- A full identity-provider integration is not implemented.
- API enforcement of these controls belongs in later integration work.
- Phase 9 should consume the security primitives without bypassing purpose and audit requirements.

## Phase 9 remaining issues
- Production authentication/identity-provider integration is still deferred.
- Dashboard data is currently served from generated CSV artifacts; a production data service remains future work.
- Dashboard UX and accessibility hardening are deferred to Phase 11.

## Deferred after Phase 9
- Phase 10 — End-to-end demonstration
- Phase 11 — Testing + hardening
- Phase 12 — Final demonstration preparation

## Phase 10 limitations / follow-up
- Workflow state is persisted in the prototype SQLite database and is not yet backed by a production database or identity provider.
- Human actor identity is represented through the existing prototype role/purpose headers; production identity federation remains future work.
- Workflow transitions are available only through the welfare-support role; no autonomous action execution exists.
- Phase 11 should harden API/UI behavior, persistence migration, audit review UX, and production-grade testing.

## Deferred after Phase 10
- Phase 11 — Testing + hardening
- Phase 12 — Final demonstration preparation



## Phase 11 — Testing + hardening
- [x] Harden SQLite workflow persistence and indexes
- [x] Serialize concurrent workflow state transitions
- [x] Invalidate dashboard cache when source artifacts change
- [x] Add repository-level hardening validator
- [x] Add Phase 11 regression tests

## Remaining Phase 11 limitations
- Production PostgreSQL migration remains future work.
- Production identity-provider integration remains future work.
- Hardware-backed TEE, attestation, and HSM-backed secrets remain production architecture work.

## Next phase
- Phase 12 — Final demonstration preparation

## Phase 12 remaining items

- Final human rehearsal in the intended Windows presentation environment.
- Confirm browser/Vite startup and screen-recording setup on the presentation machine.
- Do not add new product functionality during final demonstration preparation.

## Phase 13 remaining limitations

- The prototype still uses generated CSV artifacts instead of a production operational datastore.
- Authentication is represented by the existing prototype role/purpose boundary, not a production identity provider.
- Follow-up scheduling is represented through existing workflow states; a dedicated calendar/reminder system is outside this phase.
- Frontend package installation/build must be re-run in a normal networked development environment when dependency caches are absent.
## Phase 13.2 — Stitch Product Experience

**STATUS: COMPLETE**

Phase 13.2 implements the six-screen operational product experience from the supplied Stitch reference using the existing FORTIFY backend and security/workflow infrastructure. The screens are routed as Attention, dynamic Person Profile (`/person/:personId`), Units/Unit Command (`/units` and `/units/:unitId`), Data & Signals, Data Collection Management, and Governance/Security/Audit. Shared application chrome remains reusable across screens.

The Person Profile is fully data-driven and does not hard-code the Stitch hero example. Unit views remain aggregate-first and governance/data-management views respect the existing role/purpose authorization boundary. Raw wellness/self-report values are not emitted by the new UI.

The supplied Stitch HTML is treated as the visual and information-architecture reference; it is translated into React components rather than pasted into the application.

