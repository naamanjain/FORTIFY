# Architecture Decisions

## D-001 — Locked stack
**Decision:** React/Vite/TypeScript + Python/FastAPI + SQLite prototype + Pandas/NumPy + scikit-learn + Recharts + SciPy/deterministic optimization + cryptography/JWT/RBAC/audit/tokenization.

**Why:** The project constitution explicitly locks this stack and prohibits unnecessary framework changes.

## D-002 — SQLite for prototype
**Decision:** Use SQLite now, with PostgreSQL as the production path.

**Why:** It satisfies Phase 0 initialization without introducing an unnecessary service dependency.

## D-003 — Minimal Phase 0 frontend
**Decision:** The frontend only establishes the React/Vite foundation and verifies backend health.

**Why:** Advanced dashboard behavior belongs to later phases.

## D-004 — Minimal health API
**Decision:** Implement only `GET /health` for the Phase 0 API surface.

**Why:** It is the specified initialization contract and proves backend availability without implementing later-phase product logic.

## D-005 — No production TEE claim
**Decision:** Document the trusted-computation boundary but do not claim hardware-backed confidential computing.

**Why:** Phase 0 has no real TEE hardware or remote-attestation implementation.

## D-006 — Scenario archetypes are generator controls only
**Decision:** Use six internal operational trajectory archetypes to vary synthetic event generation, but do not write scenario labels into generated datasets.

**Why:** The prototype needs ordinary and demanding longitudinal patterns without creating a ground-truth clinical label or leakage path into future ML work.

## D-007 — Event generation is sequential
**Decision:** Generate daily event state using prior duty, prior night duty, deployment status, leave, training, incidents, and scenario parameters rather than independently randomizing every column.

**Why:** Phase 1 exists to create an operational event world with temporal relationships suitable for later analysis.

## D-008 — Optional wellness is sparse
**Decision:** Assign optional wellness reporting to a minority of personnel and a minority of days.

**Why:** The core operational world must function without wellness observations, and missing voluntary data must not become an implicit risk signal.

## D-009 — Synthetic output contains no clinical target
**Decision:** Exclude stress/mental-health scores, diagnoses, and scenario labels from generated output tables.

**Why:** Phase 1 models operational conditions only. Later phases derive analytical features from those conditions.

## D-010 — Phase 1 validation is deterministic and schema-oriented
**Decision:** Validate IDs, foreign keys, dates, bounds, categories, coverage, operational variety, and deterministic repeatability before marking Phase 1 complete.

**Why:** The generated world is an input dependency for every later phase, so silent data corruption would contaminate downstream work.

## Phase 2 decisions

### D-P2-01 — Person-day grain
Use one row per person per simulation day. This keeps rolling windows explicit and makes temporal leakage testing straightforward.

### D-P2-02 — Exact rolling boundaries
Because the person-day grid has one row per day, integer rolling windows are used: 7 means current day plus six preceding days; 30 means current day plus 29 preceding days; 90 means current day plus 89 preceding days.

### D-P2-03 — Previous-window change
“Previous” means the immediately preceding non-overlapping window of the same width. Relative change uses `(current - previous) / abs(previous)` and returns null when the previous value is zero.

### D-P2-04 — Recovery assumptions are configuration
A 6-hour short-rest threshold and 8-hour recovery target are prototype operational simulation assumptions. They are kept in `FeatureConfig` so later calibration does not require code-wide edits. They are not clinical thresholds.

### D-P2-05 — Leave delay is not fabricated
Phase 1's `status` field does not establish delayed leave semantics. The Phase 2 feature remains nullable rather than inferring a potentially misleading rule.

### D-P2-06 — Wellness missingness is preserved
Wellness values are not imputed or forward-filled. Same-day values remain missing when no voluntary observation exists; availability features describe data availability only.

### D-P2-07 — Personal-history ingredients are not baselines
Expanding personal statistics are created only as ingredients for Phase 3. No contextual baseline engine is implemented in Phase 2.

### D-P2-08 — No restoration of earlier archives
The current repository was inspected before changes and did not contain the Phase 1 implementation/data. Per the Phase 2 instruction, prior archives were not restored. Regression limitations are documented rather than hidden.


## Phase 3 decisions

### D-P3-01 — Personal baselines are strictly historical
Personal mean, median, standard deviation and deviation features use only valid observations dated before T. The current value is compared against prior history rather than included in the reference. This prevents current-day self-contamination of the reference.

### D-P3-02 — Cohort is role + deployment_type
The cohort groups personnel by existing operational attributes `role` and `deployment_type`. Unit is not included in the cohort key because that can over-fragment the sample.

### D-P3-03 — Same-day contextual references exclude self
Cohort and operational references describe the current operating context at T while removing the current person's metric from the mean. This preserves contextual interpretation without comparing a person against their own value.

### D-P3-04 — Small contexts remain missing
Cohort and operational references require a configured minimum number of comparison personnel. Repeated historical observations are never counted as additional people. This avoids falsely treating one person observed over many days as a large cohort.

### D-P3-05 — Baseline insufficiency is explicit
Missing/insufficient baseline values are left null and accompanied by count/sufficiency metadata. Null is not silently converted to zero and does not represent low risk.

### D-P3-06 — Near-zero comparisons are null-safe
Relative deviations return null when the reference magnitude is at or below the configured epsilon. This avoids unstable ratios and infinities.

### D-P3-07 — No prediction layer in Phase 3
Phase 3 only establishes contextual references. Forecasting, risk scoring, explainability, intervention, optimization, and dashboards remain deferred to later phases.

### D-P3-08 — Repository-state limitation is documented
The current inspected workspace lacked the prior implementation/data despite documentation stating those phases were complete. Previous archives were not restored because the phase instruction prohibited restoration. Regression limitations are recorded rather than masked.


## Phase 4 decisions

### D-P4-01 — Future self-report target
Use a 7-day future observed `perceived_stress_latest >= 4` target because the synthetic Phase 1 world contains sparse voluntary wellness observations and no clinical ground truth. Unobserved future wellness produces an unlabeled training row rather than a negative label.

### D-P4-02 — Wellness excluded from predictive inputs
Exclude all wellness-derived fields from Phase 4 model inputs. This prevents sparse voluntary reporting behavior from becoming an implicit risk predictor and cleanly separates target observations from predictive inputs.

### D-P4-03 — Logistic regression baseline
Use deterministic logistic regression as the first predictive model because it is simple, reproducible, auditable, and appropriate for a prototype without unnecessary model complexity.

### D-P4-04 — Chronological evaluation
Use date-based 60/20/20 train/validation/test partitions to preserve temporal ordering and reduce future-information leakage.

### D-P4-05 — Prototype risk-level thresholds
Map predicted probability to LOW/MODERATE/ELEVATED at 0.33/0.66 for prototype output. These thresholds are presentation conventions and are not clinical thresholds.

### D-P4-06 — Phase 4 remains prediction-only
Do not implement explainability/uncertainty presentation, intervention simulation, optimization, dashboards, RBAC, TEE, or LLM behavior in Phase 4.


## Phase 6 decisions

### D-P6-01 — Deterministic policy layer
Intervention selection is implemented as centralized deterministic rules rather than a new predictive model. This preserves auditability and keeps the welfare-support layer separate from Phase 5 prediction.

### D-P6-02 — One primary welfare-support action
Each person-day receives one primary action category plus an explicit human-review flag. LOW uses routine monitoring; MODERATE uses operational context to distinguish recovery support, supervisor welfare review, and wellness check-in; HIGH uses priority welfare review.

### D-P6-03 — Existing Phase 5 signals provide rationale context
Phase 6 reuses Phase 5 contributing operational signals and selected Phase 3 context features. No raw wellness values are copied into intervention output.

### D-P6-04 — Consecutive-day cooldown
Repeated identical actions on consecutive days are converted to `CONTINUE_EXISTING_SUPPORT` when risk has not materially increased. A higher risk band or configured probability increase prevents suppression. This avoids repeated duplicate interventions without hiding genuine escalation.

### D-P6-05 — No autonomous execution
Recommendations are advisory decision support for authorized human welfare personnel. No messaging, medical action, disciplinary action, or personnel allocation occurs in Phase 6.

### D-P6-06 — Operational feasibility deferred
Staffing, mandatory-role coverage, deployment requirements, and operational readiness are intentionally left to Phase 7. Phase 6 does not claim an intervention is operationally feasible.

## Phase 7 decisions
- Feasibility is deterministic and consumes Phase 6 recommendations plus same-day/previous operational events only.
- No external staffing numbers are invented; unit pressure is inferred only from existing unit/day duty totals and a configurable historical quantile reference.
- `FEASIBLE_WITH_ADJUSTMENT` is used for a single manageable timing conflict; `CONSTRAINED` for multiple active constraints or stronger workload/recovery pressure; `NOT_FEASIBLE` requires multiple hard conflicts under the prototype policy.
- Human review is required whenever Phase 6 required it or Phase 7 cannot confirm frictionless execution.
- Phase 7 is not a risk score and does not alter Phase 4–6 outputs.

## D-008 — Prototype security boundary
**Decision:** Implement application-level tokenization, authenticated encryption, purpose-bound RBAC, audit integrity logging, and an explicit trusted-computation boundary without claiming hardware-backed TEE support.

**Why:** The project architecture requires privacy/security and a trusted-computation boundary while explicitly distinguishing prototype implementation from production confidential computing. This provides testable controls without inventing hardware capabilities.

## D-009 — Deterministic analytics pseudonymization
**Decision:** Use HMAC-SHA256 with an externally supplied secret for deterministic personnel tokens.

**Why:** Analytics components can consistently correlate the same person without receiving the raw personnel identifier. HMAC avoids reversible identifier encoding and keeps the mapping secret outside the analytics code.

## D-010 — Purpose-bound access
**Decision:** Authorize access using both role and declared purpose.

**Why:** Infrastructure administration should not automatically imply welfare-data access, and commanders should not automatically receive individual welfare information.


## Phase 11 — Testing + hardening
- Keep hardening changes beneath the existing Phase 9/10 interfaces.
- Use SQLite `BEGIN IMMEDIATE` for workflow transitions so concurrent requests cannot both act on the same stale state.
- Enable SQLite foreign-key enforcement and a bounded busy timeout for workflow persistence.
- Add indexes instead of changing workflow query semantics.
- Cache generated decision inputs only with file-signature invalidation so updated artifacts are observed without changing normal behavior.
- Validate existing artifacts and security boundaries rather than regenerating earlier phases.

## Phase 12 decisions

### D-P12-01 — Deterministic hero-case selection
Select the hero case from existing Phase 5–7 outputs using a deterministic policy: the largest 21-day increase in model probability among cases ending HIGH with `PRIORITY_WELFARE_REVIEW`, a constrained/adjusted feasibility state, and at least two existing constraint flags. Tie-break by person ID/date. This produces a reproducible demonstration anchor without altering any runtime decision logic.

### D-P12-02 — Demo preparation is read-only
Phase 12 reads existing generated artifacts and workflow state but does not mutate workflow states, append audit events, or rewrite Phase 1–11 artifacts. Human workflow actions remain part of the live Phase 10 demonstration step.

### D-P12-03 — No raw wellness in demo artifacts
The demonstration timeline and manifest expose only operational decision-support information already present in Phase 5–7 outputs. Raw voluntary wellness responses are excluded.

## Phase 13 decisions

- The existing dashboard was extended rather than replaced with a second application.
- Product navigation follows the three conceptual layers from the UX blueprint: ACT, UNDERSTAND, GOVERN.
- Command access is aggregate-first; individual welfare detail remains purpose-bound.
- Global search is implemented as a backend aggregation endpoint so access policy is enforced server-side.
- Provenance/status screens expose metadata only; raw event and wellness values are not sent to the browser.
- Existing Phase 10 workflow transitions remain the only mechanism for changing workflow state.
