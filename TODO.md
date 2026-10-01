# TODO — Status and Remaining Limitations

All planned prototype phases (0–13.2) are complete. This document tracks what the prototype
genuinely does **not** do. It replaces the earlier per-phase "deferred" lists, which had drifted
out of sync with the completed roadmap.

## Completed

- Phase 0 — Project initialization
- Phase 1 — Synthetic operational world
- Phase 2 — Feature engineering
- Phase 3 — Personal + cohort + operational baselines
- Phase 4 — Predictive risk modeling
- Phase 5 — Risk decision layer (calibration + threshold + explanations)
- Phase 6 — Welfare intervention / decision support
- Phase 7 — Operational constraint engine
- Phase 8 — Privacy + security controls (application level)
- Phase 9 — Dashboard integration
- Phase 10 — End-to-end human-in-the-loop workflow
- Phase 11 — Testing + hardening
- Phase 12 — Final demonstration preparation
- Phase 13 / 13.2 — Operational product experience (Stitch six-screen UX)

## Standing limitations (not scheduled — they are out of prototype scope)

**Data and model**
- All data is synthetic. No clinical, operational, or external validation exists or is claimed.
- The supervised target depends on sparse voluntary wellness self-reports; most person-days are
  unlabeled for evaluation.
- Explanations are associative operational signals, not causal explanations.
- The operating threshold (0.45) and risk bands are synthetic-prototype tuning and require policy
  review before any real-world use.

**Security and identity**
- There is no authentication: the API trusts `X-Fortify-Role` / `X-Fortify-Purpose` headers.
  Trusted-network demonstration only.
- No production identity provider / identity federation.
- No HSM-backed secret management, hardware-backed TEE, remote attestation, or hardware-backed key
  release — Phase 8 implements application-level controls and an explicit trust boundary only.

**Platform**
- Prototype SQLite persistence; production PostgreSQL migration is future work.
- Dashboard reads regenerated CSV artifacts through read-only endpoints; a production data service
  is out of scope.
- Follow-up scheduling is represented through workflow states; no calendar/reminder integration.
- Workflow actor identity uses the prototype role/purpose headers, not real federated identity.

**Product boundary**
- Recommendations are deterministic policy outputs routed to human review; the system never
  executes interventions, sends messages, or takes autonomous or adverse personnel action.
- No numeric intervention simulator: Phase 6/7 provide action mapping and feasibility flags, not
  projected-strain estimates (see PRODUCT_SPEC.md honesty note).

## Demonstration follow-ups (manual, not code)

- Final human rehearsal in the intended Windows presentation environment
  ([docs/DEMO_RUNBOOK.md](docs/DEMO_RUNBOOK.md)).
- Confirm browser/Vite startup and screen-recording setup on the presentation machine.
- Do not add new product functionality during final demonstration preparation.
