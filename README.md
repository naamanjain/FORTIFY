# FORTIFY

**Force Operational Resilience & Timely Intervention Framework**

SIH Problem Statement: **26186**  
Title: **AI-Based Predictive Personnel Stress and Welfare Monitoring System for Uniformed Forces**  
Organization: **Ministry of Home Affairs — CRPF, Police II Division**  
Category: **Software**  
Domain: **MedTech / BioTech / HealthTech**

## Current phase

**Phase 4 — Predictive Risk Modeling (complete)**

Phase 0 established the React/Vite/TypeScript frontend, Python/FastAPI backend, SQLite prototype, health endpoint, and locked architecture. Phase 1 now supplies a deterministic synthetic longitudinal operational world for later analytical phases.

## Phase 1 data generation

Default dataset:

```bash
python scripts/generate_synthetic_data.py --personnel 500 --days 180 --seed 42 --output data/generated
```

Custom example:

```bash
python scripts/generate_synthetic_data.py \
  --personnel 500 \
  --days 180 \
  --seed 42 \
  --output data/generated
```

Optional parameters also include `--start-date` and `--wellness-coverage`.

## Validate generated data

```bash
python scripts/validate_synthetic_data.py \
  --output data/generated \
  --personnel 500 \
  --days 180
```

The validator checks file presence, unique IDs, valid foreign keys, temporal ordering, duration bounds, categorical values, personnel coverage, night duty representation, event variety, sparse wellness coverage, and prohibited clinical/scenario fields.

## Phase 1 outputs

Generated under `data/generated/`:

- `personnel.csv`
- `units.csv`
- `deployment_events.csv`
- `duty_events.csv`
- `recovery_events.csv`
- `leave_events.csv`
- `training_events.csv`
- `incident_events.csv`
- `wellness_events.csv`
- `README.md`

Formal schemas are under `data/schemas/`.

## Run tests

From the repository root:

```bash
PYTHONPATH=. pytest -q backend/tests/test_health.py backend/tests/test_phase1_data.py
```

The full backend test suite can also be run from `backend/` with the Phase 0 test environment configured.

## Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

## Phase boundaries

Phase 4 now implements the first predictive risk-modeling layer only. Phase 5 explainability/uncertainty, intervention simulation, optimization, advanced dashboard behavior, production authentication, and TEE remain deferred.

All generated data is synthetic, is not real government data, and is not clinically validated.

## Phase 2 — Feature Engineering

Build time-aware person-day features from the existing Phase 1 CSV world:

```bash
python scripts/build_features.py --input data/generated --output data/generated
```

Validate the resulting feature table:

```bash
python scripts/validate_features.py --input data/generated/person_day_features.csv --personnel 500 --days 180
```

Feature metadata: `data/schemas/feature_schema.json` and `data/generated/FEATURE_CATALOG.md`.

Phase 2 performs feature transformation only. It does not train ML models, calculate risk, forecast trajectory, establish final baselines, explain predictions, simulate interventions, optimize operations, or implement the dashboard.


## Phase 3 — Personal + Cohort + Operational Baselines

The Phase 3 baseline engine extends the person-day feature table with contextual references:

```bash
python scripts/build_baselines.py --input data/generated/person_day_features.csv --output data/generated/person_day_features.csv
```

Validate the extended table:

```bash
python scripts/validate_baselines.py --input data/generated/person_day_features.csv
```

Baseline assumptions are configurable in `backend/app/ml/baseline_config.py`. Personal history requires 14 valid prior observations by default; cohort and operational context require 10 comparison personnel. Small/insufficient contexts remain missing.

Phase 3 does not train a model, calculate risk, forecast trajectory, recommend interventions, optimize operations, or implement a dashboard. Phase 4 is the next phase only after Phase 3 cross-phase integration verification passes.


## Phase 4 — Predictive Risk Modeling

Train the deterministic baseline model from the Phase 3 table:

```bash
python scripts/train_model.py --input data/generated/person_day_features_baseline.csv --output-dir artifacts/phase4 --prediction-output data/generated/risk_predictions.csv
```

Validate the generated predictive artifacts:

```bash
python scripts/validate_model.py
```

The Phase 4 target uses observed synthetic voluntary wellness in the next 7 days. Wellness-derived fields are excluded from predictive inputs. Model outputs are operational/welfare prototype signals, not clinical diagnoses or validated medical predictions.

## Phase 5 — Risk Decision Layer
Build the Phase 5 welfare decision layer from the existing Phase 4 predictions:

```bash
python scripts/build_phase5_risk_layer.py --features data/generated/person_day_features_baseline.csv --phase4-model artifacts/phase4/fortify_phase4_logistic_regression.joblib --phase4-metadata artifacts/phase4/model_metadata.json --phase4-predictions data/generated/risk_predictions.csv --output-dir artifacts/phase5 --prediction-output data/generated/risk_decisions.csv --seed 42
```

Validate the Phase 5 output:

```bash
python scripts/validate_phase5_risk_layer.py
```

The locked prototype operating threshold is selected from validation data with a recall floor; test labels are not used for threshold selection or calibration. Risk bands are LOW/MODERATE/HIGH operational welfare signals only. Raw wellness responses are not exposed in the Phase 5 decision output.



## Phase 6 — Welfare Intervention / Decision Support
Build deterministic welfare-support recommendations from the Phase 5 decision output:

```bash
python scripts/build_interventions.py --predictions data/generated/risk_decisions.csv --features data/generated/person_day_features_baseline.csv --output data/generated/intervention_recommendations.csv --report data/generated/intervention_generation_report.json
```

Validate:

```bash
python scripts/validate_interventions.py --input data/generated/intervention_recommendations.csv --report data/generated/intervention_generation_report.json
```

Phase 6 is policy-only: it maps LOW/MODERATE/HIGH signals to welfare-support action categories, generates operational rationales, requires human review where appropriate, and suppresses unchanged repeated recommendations. It does not execute interventions, send messages, optimize staffing, or make clinical/disciplinary decisions.

## Phase 7 — operational feasibility
Run from the repository root:

```bash
python scripts/build_feasibility.py
python scripts/validate_feasibility.py --expected-rows 90000
```

Phase 7 consumes `data/generated/intervention_recommendations.csv` and existing operational event datasets. It writes `data/generated/intervention_feasibility.csv` and `data/generated/feasibility_generation_report.json`.

## Phase 8 security controls

Run the Phase 8 security validation from the repository root:

```bash
python scripts/validate_security.py
```

The validation checks identity pseudonymization, authenticated encryption round-trip, purpose-bound access control, audit-chain integrity, the trusted-computation boundary, and the absence of raw wellness fields from operational outputs.

The prototype does not claim hardware-backed TEE or remote attestation. Those are production architecture requirements.

## Phase 9 — Dashboard

Run the backend and frontend independently. The dashboard reads existing Phase 5–8 artifacts through read-only FastAPI dashboard endpoints. No raw wellness/self-report fields are sent to the browser.

Backend:
```bash
uvicorn app.main:app --reload --port 8000
```

Frontend:
```bash
cd frontend
npm install
npm run dev
```

Dashboard validation:
```bash
python scripts/validate_dashboard.py
```

The prototype frontend sends role/purpose headers for the existing Phase 8 authorization boundary. Production authentication remains deferred.

## Phase 10 — Human-in-the-loop workflow
The dashboard now exposes a deterministic workflow over Phase 6/7 decisions. Authorized welfare personnel can inspect pending items and record explicit state transitions such as acknowledgement, review, support planning, deferral, dismissal, and completion. Every transition is audited.

The workflow does not execute interventions, send messages, or make adverse personnel decisions.

Run the backend as before:
```bash
uvicorn app.main:app --reload --port 8000
```

The Phase 10 API is under `/api/workflow/` and uses the existing `X-Fortify-Role` / `X-Fortify-Purpose` prototype security boundary.



## Phase 11 — Testing + hardening

Phase 11 adds prototype hardening around the existing Phase 9 dashboard and Phase 10 workflow. It strengthens SQLite workflow persistence, serializes concurrent workflow transitions, invalidates dashboard caches when source artifacts change, and provides a root-level validation command. It does not change prediction, risk bands, intervention policy, feasibility semantics, or security roles.

Run the hardening validator from the project root:

```text
python scripts/validate_hardening.py
```

The prototype remains synthetic and is not a clinical, disciplinary, or production security system.

## Phase 12 — Final Demonstration Preparation

Prepare the deterministic synthetic demonstration package:

```bash
python scripts/prepare_demo.py
```

Validate it:

```bash
python scripts/validate_demo.py
```

Outputs are written under `artifacts/phase12/` and contain no raw wellness responses. The preparation step is read-only with respect to workflow state and earlier generated artifacts.

## Phase 13 — Operational Product Experience

Run the existing backend as normal, then start the frontend with `npm run dev` from `frontend/`.

The dashboard now provides role-aware operational navigation for Attention, Follow-ups, Personnel, Units, Trends, Data & Signals, and governance views. The browser receives aggregated operational context rather than raw event/feature datasets.

Validate the product layer from the repository root:

```bash
python scripts/validate_product_experience.py
pytest -q
```

Individual personnel views require `WELFARE_OFFICER` + `WELFARE_SUPPORT`. Aggregate command views use `AGGREGATE_OPERATIONS`. Governance views use the existing auditor/administrator purposes. The interface is a synthetic demonstration environment and not a clinical or disciplinary system.
## Phase 13.2 — Stitch Product Experience

**STATUS: COMPLETE**

Phase 13.2 implements the six-screen operational product experience from the supplied Stitch reference using the existing FORTIFY backend and security/workflow infrastructure. The screens are routed as Attention, dynamic Person Profile (`/person/:personId`), Units/Unit Command (`/units` and `/units/:unitId`), Data & Signals, Data Collection Management, and Governance/Security/Audit. Shared application chrome remains reusable across screens.

The Person Profile is fully data-driven and does not hard-code the Stitch hero example. Unit views remain aggregate-first and governance/data-management views respect the existing role/purpose authorization boundary. Raw wellness/self-report values are not emitted by the new UI.

The supplied Stitch HTML is treated as the visual and information-architecture reference; it is translated into React components rather than pasted into the application.

