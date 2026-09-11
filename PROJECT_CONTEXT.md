# FORTIFY — Project Context

## Project identity
- Name: FORTIFY
- Expansion: Force Operational Resilience & Timely Intervention Framework
- SIH problem statement: 26186
- Title: AI-Based Predictive Personnel Stress and Welfare Monitoring System for Uniformed Forces
- Organization: Ministry of Home Affairs, Central Reserve Police Force (CRPF), Police II Division
- Category: Software
- Domain: MedTech / BioTech / HealthTech

## Problem
Uniformed personnel operate under prolonged deployments, irregular/night duties, operational workload, inadequate recovery, family separation, transfers, training commitments, and demanding operational incidents. Existing welfare intervention may be reactive and depend heavily on manual observation or voluntary self-reporting.

## Product definition
FORTIFY is a privacy-preserving operational welfare decision-support platform. It is intended to analyze longitudinal operational patterns and, when voluntarily available, wellness information to identify emerging welfare strain, contextualize it against baselines, estimate trajectory, explain contributors, simulate interventions, evaluate operational constraints, recommend an intervention to an authorized welfare decision-maker, and observe outcomes.

Core loop: `OBSERVE → CONTEXTUALIZE → FORECAST → SIMULATE → CONSTRAIN → RECOMMEND → VERIFY`

## Boundaries
FORTIFY is not a diagnosis, depression/anxiety detector, suicide predictor, disciplinary/performance scoring system, surveillance system, facial/voice emotion recognizer, mandatory daily survey, wearable-first product, LLM therapist, generic chatbot, or replacement for trained welfare/medical professionals.

## Data strategy
Prototype data is synthetic longitudinal operational data. Real government personnel data is not required. Voluntary wellness data is supplementary; missing voluntary fields must not be treated as elevated risk and the core operational world works without them.

## Locked stack
- Frontend: React, Vite, TypeScript, Recharts
- Backend: Python, FastAPI
- Prototype database: SQLite; production path: PostgreSQL
- Data: Pandas, NumPy
- ML: scikit-learn
- Optimization: SciPy where appropriate or deterministic constraint/optimization logic
- Security: Python cryptography libraries, JWT/RBAC, audit logging, tokenization

## Current phase
**Phase 11 — Testing + hardening (complete)**

## Completed phases
- Phase 0: Project initialization
- Phase 1: Synthetic Operational World
- Phase 2: Feature Engineering

## Current implementation status
- Locked repository architecture preserved.
- React/Vite/TypeScript frontend and FastAPI/SQLite backend from Phase 0 preserved.
- Deterministic Phase 1 generator added at `scripts/generate_synthetic_data.py`.
- Phase 1 dataset validator added at `scripts/validate_synthetic_data.py`.
- Formal dataset schemas added under `data/schemas/`.
- Default synthetic dataset generated under `data/generated/` using 500 personnel, 180 days, seed 42.
- Generated README added at `data/generated/README.md`.
- Phase 1 tests added under `backend/tests/test_phase1_data.py`.
- Small dataset generation, default dataset generation, validation, deterministic generation, foreign-key integrity, and temporal integrity have been executed successfully.

## Default dataset result
- Personnel: 500
- Units: 18
- Duty events: 82,166
- Recovery events: 90,000
- Leave events: 918
- Deployment events: 291
- Training events: 7,209
- Incident events: 4,369
- Wellness events: 7,129
- Wellness personnel coverage: 35.4%
- Generation-only scenario allocation: STABLE 84, HIGH_LOAD 84, RECOVERY_DEFICIT 83, PROLONGED_DEPLOYMENT 83, VOLATILE 83, RECOVERY_AFTER_PEAK 83

## Known limitations
- Unit and event distributions are synthetic prototype assumptions, not real organizational statistics.
- Optional wellness responses are synthetic and not clinically validated.
- Phase 2 feature-engineering layer implemented under `backend/app/ml/`.
- Phase 2 focused tests pass, including explicit future-leakage and rolling-boundary tests.
- Phase 4 predictive risk-modeling layer implemented and validated on the full 90,000-row Phase 3 table.
- Phase 6 welfare-support policy and Phase 7 feasibility layers are implemented.
- Phase 8 prototype security controls are implemented; hardware-backed TEE and production identity/security infrastructure remain deferred.

## Next phase
**PHASE 9 — Dashboard Integration**


## Phase 4 implementation status
**STATUS: Phase 4 — Predictive Risk Modeling (complete)**

Phase 4 consumes the existing Phase 3 baseline-extended person-day table. The predictive target is an observed synthetic voluntary-wellness outcome: whether `perceived_stress_latest` reaches 4 or 5 on any observed day in the following 7 days. This is not clinical ground truth and is not a psychiatric or medical diagnosis.

The model is a deterministic scikit-learn logistic-regression baseline with median imputation for numeric operational features, standardization, one-hot encoding for supported categorical context, and class weighting. All wellness-derived columns are excluded from model inputs so missing voluntary reporting cannot become an implicit risk feature.

Temporal evaluation uses chronological train/validation/test partitions. The 90,000-row Phase 3 table yielded 26,085 usable labeled prediction dates; 63,915 rows had no observed future wellness within the 7-day target horizon and were excluded from supervised training but still receive predictions from the trained model.

Full-data test ROC AUC: 0.7634. Test average precision: 0.5791. These are synthetic-prototype evaluation metrics, not clinical validation or operational performance claims.

Artifacts:
- `backend/app/ml/model_config.py`
- `backend/app/ml/target_engineering.py`
- `backend/app/ml/model_training.py`
- `backend/app/ml/model_evaluation.py`
- `scripts/train_model.py`
- `scripts/validate_model.py`
- `artifacts/phase4/fortify_phase4_logistic_regression.joblib`
- `artifacts/phase4/model_metadata.json`
- `artifacts/phase4/evaluation_report.json`
- `data/generated/risk_predictions.csv`
- `backend/tests/test_phase4_model.py`

Reproducibility was verified twice on the full dataset: prediction and metadata SHA-256 hashes matched exactly with the same seed/configuration.

## Important decisions
- SQLite remains the prototype database.
- Longitudinal data is a first-class architectural requirement.
- Synthetic-data generation is isolated from prediction logic.
- Scenario archetypes are generation controls, not ML ground-truth labels.
- Optional wellness data is sparse and non-required.
- Human authorized welfare professionals remain responsible for intervention decisions.

## Development commands
Generate default data:

```bash
python scripts/generate_synthetic_data.py --personnel 500 --days 180 --seed 42 --output data/generated
```

Validate:

```bash
python scripts/validate_synthetic_data.py --output data/generated --personnel 500 --days 180
```

Run tests:

```bash
PYTHONPATH=. pytest -q backend/tests/test_health.py backend/tests/test_phase1_data.py
```


## Phase 2 implementation status
**STATUS: Phase 2 — Feature Engineering (complete)**

Phase 2 produced the deterministic 90,000-row person-day feature table with 104 engineered operational features and explicit temporal-leakage tests.

## Phase 3 implementation status
**STATUS: Phase 3 — Personal + Cohort + Operational Baselines (complete)**

Phase 3 extended the person-day table with 145 contextual baseline/reference features. Personal statistics are strictly prior-day; cohort and operational references are same-day, self-excluded aggregates with sufficiency guards.

## Phase 4 implementation status
**STATUS: Phase 4 — Predictive Risk Modeling (complete)**

Phase 4 consumes the 90,000-row Phase 3 baseline-extended table. The supervised target is `future_high_perceived_stress_7d`: whether observed synthetic voluntary `perceived_stress_latest` reaches 4 or 5 on any day in T+1..T+7. This is an observed synthetic self-report target, not clinical ground truth.

The model is deterministic scikit-learn logistic regression using operational/context and Phase 3 baseline features. Wellness-derived fields are excluded from model inputs. Temporal evaluation uses chronological train/validation/test dates.

Full-data result: 26,085 usable labeled rows, 63,915 unlabeled rows, 218 model features, 15,662/5,325/5,098 train/validation/test rows, validation ROC AUC 0.74575, test ROC AUC 0.76340, test average precision 0.57910. These metrics are synthetic-prototype metrics only.

Artifacts: `artifacts/phase4/fortify_phase4_logistic_regression.joblib`, `artifacts/phase4/model_metadata.json`, `artifacts/phase4/evaluation_report.json`, and `data/generated/risk_predictions.csv`. Same-seed full-data prediction and metadata hashes matched exactly.

## Known limitations
- Synthetic unit/event distributions are prototype assumptions, not real organizational statistics.
- Optional wellness responses are synthetic and not clinically validated.
- Phase 4 target availability depends on voluntary future observations, so many person-days are unlabeled for supervised training.
- The Phase 4 model is a prototype predictive baseline and is not externally validated or clinically calibrated.
- Phase 5 explainability and uncertainty work is not implemented.
- No intervention simulator, operational constraint engine, production authentication, or hardware-backed TEE is implemented.

## Important decisions
- SQLite remains the prototype database.
- Longitudinal data is a first-class architectural requirement.
- Synthetic-data generation is isolated from prediction logic.
- Scenario archetypes are generation controls, not ML ground-truth labels.
- Optional wellness data is sparse and non-required.
- Wellness-derived fields are excluded from Phase 4 model inputs.
- Human authorized welfare professionals remain responsible for intervention decisions.

## Development commands
Generate default data:

```bash
python scripts/generate_synthetic_data.py --personnel 500 --days 180 --seed 42 --output data/generated
```

Validate:

```bash
python scripts/validate_synthetic_data.py --output data/generated --personnel 500 --days 180
python scripts/validate_features.py --input data/generated/person_day_features.csv --personnel 500 --days 180
python scripts/validate_baselines.py --input data/generated/person_day_features_baseline.csv --personnel 500 --days 180
```

Train Phase 4:

```bash
python scripts/train_model.py --input data/generated/person_day_features_baseline.csv --output-dir artifacts/phase4 --prediction-output data/generated/risk_predictions.csv
```

Validate Phase 4:

```bash
python scripts/validate_model.py
```

Run tests:

```bash
pytest -q
```

## Phase 5 — Risk Decision Layer
Phase 5 converts the Phase 4 probability output into a validation-locked operational/welfare early-warning signal. The existing Phase 4 Logistic Regression and `risk_predictions.csv` are preserved.

The Phase 5 decision layer applies Platt calibration fitted on validation predictions only, evaluates candidate thresholds on validation data, and locks the highest-validation-F1 threshold meeting a minimum 0.80 validation recall. The selected threshold is 0.25 for the current synthetic dataset. Risk bands are deterministic: LOW < 0.25, MODERATE 0.25–<0.50, HIGH >= 0.50. These are operational/welfare monitoring signals, not clinical categories.

The frontend-consumable output is `data/generated/risk_decisions.csv`. It contains person ID, date, calibrated welfare-risk probability, risk band, threshold decision, threshold/model metadata, and non-clinical contributing operational signals. Raw wellness responses are not emitted.

Phase 5 full-data validation used 26,085 labeled rows for threshold/calibration evaluation and preserved all 90,000 person-day prediction rows in the decision output. Test labels were not used for threshold selection or calibration.

## Current phase
**PHASE 5 — Risk Decision Layer — COMPLETE**

## Next phase
**PHASE 6 — Intervention Simulator**

## Phase 6 — Welfare Intervention / Decision Support
Phase 6 adds a deterministic welfare-support policy layer on top of the Phase 5 `risk_decisions.csv` output. It produces one recommendation per person-day without retraining the predictive model, changing the target, or executing an intervention.

Policy actions are centralized in `backend/app/ml/intervention_config.py`. LOW maps to `ROUTINE_MONITORING`; MODERATE maps to `RECOVERY_SUPPORT`, `SUPERVISOR_WELFARE_REVIEW`, or `WELLNESS_CHECK_IN` based on existing operational context; HIGH maps to `PRIORITY_WELFARE_REVIEW`. Human-review flags are explicit.

Cooldown suppression converts repeated identical recommendations on consecutive days into `CONTINUE_EXISTING_SUPPORT` when risk has not materially increased. A risk-band increase or configured probability increase breaks cooldown.

Output: `data/generated/intervention_recommendations.csv`. Report: `data/generated/intervention_generation_report.json`.

Full-data Phase 6 validation: 90,000 person-days, 500 personnel. Full pytest: 42 passed before the final Phase 6 test additions and 52 passed after them. The full current suite is the authoritative regression result.

## Current phase
**PHASE 6 — Welfare Intervention / Decision Support — COMPLETE**

## Next phase
**PHASE 7 — Operational Constraint Engine**

## Phase 7 — Operational Feasibility / Constraint Layer
Phase 7 consumes Phase 6 intervention recommendations and existing same-day operational data to determine whether the recommended welfare-support action is operationally feasible at the recommendation date. It does not alter Phase 4 prediction, Phase 5 risk decisions, or Phase 6 policy mapping.

Feasibility states are `FEASIBLE`, `FEASIBLE_WITH_ADJUSTMENT`, `CONSTRAINED`, and `NOT_FEASIBLE`. Constraint signals are derived only from existing synthetic duty, recovery, leave, deployment, training, and unit-level duty data. No external staffing numbers or operational facts are introduced.

All feasibility decisions use data available on or before the recommendation date. No future events are used. The output is `data/generated/intervention_feasibility.csv` with report `data/generated/feasibility_generation_report.json`.

Current phase: **PHASE 7 — Operational Feasibility / Constraint Layer — COMPLETE**

Next phase: **PHASE 8 — Privacy + Security + TEE Architecture**

## Phase 8 implementation status
**STATUS: Phase 8 — Privacy + Security + TEE Architecture (complete)**

Phase 8 adds reusable prototype security controls under `backend/app/security/`: deterministic HMAC pseudonymization for personnel identifiers, authenticated encryption utilities for protected blobs, purpose-bound role authorization, append-only audit logging with a SHA-256 hash chain, and an explicit trusted-computation boundary.

The trusted-computation boundary is intentionally application-process based in the prototype. Hardware-backed TEE, remote attestation, confidential VMs, and hardware-backed key release are not claimed as implemented.

Phase 8 does not alter Phase 4–7 prediction, risk, welfare-policy, or feasibility semantics. It provides security primitives and validation that later API/dashboard layers can consume.

Phase 8 validation report: `artifacts/phase8/security_control_report.json`.

## Next phase
**PHASE 9 — Dashboard Integration**

## Phase 9 implementation status
**STATUS: Phase 9 — Dashboard Integration (complete)**

The Phase 9 dashboard is a read-only operational welfare presentation layer over existing Phase 5–8 artifacts. It uses FastAPI aggregation endpoints and React/Vite/TypeScript/Recharts presentation. The browser does not receive raw wellness/self-report fields or the complete 90,000-row operational datasets. Dashboard requests use the Phase 8 purpose-bound security primitives in the prototype via explicit role/purpose headers. Individual person detail is restricted to the welfare-support role/purpose.

Dashboard endpoints:
- `GET /api/dashboard/overview`
- `GET /api/dashboard/trend?days=30`
- `GET /api/dashboard/units`
- `GET /api/dashboard/person/{person_id}`

Phase 9 does not change Phase 4–8 artifacts or decision logic.

## Phase 9 limitations
- Prototype dashboard security headers are an application-level enforcement boundary, not a production identity provider.
- Dashboard data is read from generated CSV artifacts rather than a production database/API-backed domain store.
- The dashboard exposes operational welfare signals only; raw voluntary wellness observations remain excluded.
- Phase 10 remains the end-to-end demonstration phase.

## Phase 10 — Human-in-the-loop intervention workflow
**STATUS: COMPLETE**

Phase 10 adds a persisted, deterministic workflow state model over the Phase 6 recommendation + Phase 7 feasibility stream. Workflow records start in `NEW` and can only move through explicitly allowed human transitions. Individual transitions require the existing Phase 8 `WELFARE_OFFICER` + `WELFARE_SUPPORT` authorization.

Workflow state is persisted in the prototype SQLite database; no prior generated Phase 1–9 artifact is rewritten. Every transition is recorded in both the workflow audit table and the existing Phase 8 append-only audit log. Audit records contain workflow/reference metadata only and never raw voluntary wellness responses.

The Phase 9 dashboard now includes a pending workflow queue and a human review panel for viewing the recommendation, feasibility, current workflow state, available transitions, and audit history. No transition is automatic and terminal states (`COMPLETED`, `DISMISSED`) cannot be changed.

## Current phase
**PHASE 10 — Human-in-the-loop intervention workflow — COMPLETE**

## Next phase
**PHASE 11 — Testing + hardening**



## Phase 11 — Testing + Hardening
**STATUS: COMPLETE**

Phase 11 hardens the existing prototype without changing the predictive or welfare-decision semantics. It adds idempotent SQLite workflow indexes, explicit foreign-key and busy-timeout configuration, serialized workflow transitions using SQLite `BEGIN IMMEDIATE`, source-artifact-aware dashboard cache invalidation, and a repository-level hardening validator. Phase 11 also adds regression coverage for repeated workflow initialization, concurrent state changes, audit tamper detection, SQLite foreign-key enforcement, dashboard cache invalidation, and artifact/privacy contracts.

Phase 11 remains a prototype hardening layer. It does not introduce production identity federation, database migrations to PostgreSQL, HSM-backed secrets, hardware TEE, or new welfare/prediction logic.

## Current phase
**Phase 11 — Testing + hardening (complete)**

## Next phase
**Phase 12 — Final demonstration preparation**

## Phase 12 — Final Demonstration Preparation
**STATUS: COMPLETE**

Phase 12 adds a deterministic final-demonstration preparation layer on top of the completed Phase 9–11 product flow. It selects a reproducible synthetic hero case from the existing risk, intervention, and feasibility artifacts, exports a 22-day operational/risk timeline, records the workflow starting state without mutating it, and produces a machine-readable demonstration manifest plus readiness report. No raw voluntary wellness responses are included.

Current prepared hero case: `P-0002` on `2026-02-25`. The case was selected deterministically because it ends with a HIGH operational/welfare signal, `PRIORITY_WELFARE_REVIEW`, and multiple existing feasibility constraints after the largest qualifying 21-day increase in model probability.

Phase 12 does not change Phase 4–11 decision semantics and does not execute workflow actions automatically. The final walkthrough remains human-led and uses synthetic demonstration data only.

## Current phase
**PHASE 12 — Final Demonstration Preparation — COMPLETE**

## Next phase
**NONE — LOCKED ROADMAP COMPLETE**

## Phase 13 — Operational Product Experience
**STATUS: COMPLETE**

Phase 13 implements the operational product experience defined by the product/UX blueprint. The existing dashboard is now organized around Attention, Follow-ups, Personnel, Units, Trends, Data & Signals, Audit, and System Health using the existing FastAPI + React/Vite/TypeScript/Recharts stack.

The product remains aggregate-first for command access and purpose-bound for individual welfare views. Global search is role-aware, data provenance is exposed as metadata rather than raw records, governance views use the existing Phase 8 authorization boundary, and Phase 10 workflow actions remain the only path for human state changes.

Phase 13 does not change prediction, risk bands, intervention policy, feasibility logic, security primitives, workflow states, or generated operational artifacts. It adds presentation/navigation and read-only aggregation needed to expose the completed decision loop as an operational application.

## Current phase
**PHASE 13 — Operational Product Experience — COMPLETE**

## Next phase
**NONE — Phase 13 is the current final product-experience scope in the supplied roadmap/blueprint.**
## Phase 13.2 — Stitch Product Experience

**STATUS: COMPLETE**

Phase 13.2 implements the six-screen operational product experience from the supplied Stitch reference using the existing FORTIFY backend and security/workflow infrastructure. The screens are routed as Attention, dynamic Person Profile (`/person/:personId`), Units/Unit Command (`/units` and `/units/:unitId`), Data & Signals, Data Collection Management, and Governance/Security/Audit. Shared application chrome remains reusable across screens.

The Person Profile is fully data-driven and does not hard-code the Stitch hero example. Unit views remain aggregate-first and governance/data-management views respect the existing role/purpose authorization boundary. Raw wellness/self-report values are not emitted by the new UI.

The supplied Stitch HTML is treated as the visual and information-architecture reference; it is translated into React components rather than pasted into the application.

