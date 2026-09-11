# Roadmap

The development sequence is locked.

- Phase 0 — Project initialization **(completed)**
- Phase 1 — Synthetic operational world **(completed)**
- Phase 2 — Feature engineering **(completed)**
- Phase 3 — Personal + cohort + operational baselines **(completed)**
- Phase 4 — Predictive Risk Modeling **(completed)**
- Phase 5 — Risk Decision Layer / Explainability + uncertainty **(completed)**
- Phase 6 — Welfare Intervention / Decision Support **(completed)**
- Phase 7 — Operational Feasibility / Constraint Layer **(completed)**
- Phase 8 — Privacy + Security + TEE Architecture **(completed)**
- Phase 9 — Dashboard integration **(completed)**
- Phase 10 — End-to-end demonstration **(completed)**
- Phase 11 — Testing + hardening **(completed)**
- Phase 12 — Final demonstration preparation **(not started)**

**Current phase: Phase 11 — Testing + hardening (complete)**
**Next phase: Phase 12 — Final demonstration preparation**

Do not skip ahead.

## Phase 12 — Final Demonstration Preparation

**STATUS: COMPLETE**

Phase 12 prepared a deterministic synthetic hero case, a 22-day demonstration timeline, a machine-readable demo manifest, and a readiness report. It does not alter prior-phase artifacts or workflow state.

**Roadmap status: COMPLETE through Phase 12.**

## Phase 13 — Operational Product Experience
**STATUS: COMPLETE**

Phase 13 implements the operational product experience from the supplied UX blueprint: role-aware application shell, Attention/Follow-ups, Personnel, aggregate-first Units, Trends, Data & Signals, Audit, System Health, global search, responsive behavior, and integration with the existing Phase 10 workflow. No completed backend decision semantics are replaced.
## Phase 13.2 — Stitch Product Experience

**STATUS: COMPLETE**

Phase 13.2 implements the six-screen operational product experience from the supplied Stitch reference using the existing FORTIFY backend and security/workflow infrastructure. The screens are routed as Attention, dynamic Person Profile (`/person/:personId`), Units/Unit Command (`/units` and `/units/:unitId`), Data & Signals, Data Collection Management, and Governance/Security/Audit. Shared application chrome remains reusable across screens.

The Person Profile is fully data-driven and does not hard-code the Stitch hero example. Unit views remain aggregate-first and governance/data-management views respect the existing role/purpose authorization boundary. Raw wellness/self-report values are not emitted by the new UI.

The supplied Stitch HTML is treated as the visual and information-architecture reference; it is translated into React components rather than pasted into the application.

