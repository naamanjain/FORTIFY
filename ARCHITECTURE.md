# Architecture

## Locked technology
React + Vite + TypeScript + Recharts; Python + FastAPI; SQLite prototype with PostgreSQL production path; Pandas + NumPy; scikit-learn; SciPy or deterministic constraint logic; cryptography libraries, JWT/RBAC, audit logging, tokenization.

## Major layers
- Frontend: presentation, pages, components, charts, simulator UI, service calls, types, styles.
- API: FastAPI routes and transport boundary.
- Core: configuration and database initialization.
- Models: API/domain schemas.
- Services: application services.
- ML: feature/baseline/forecasting modules in later phases.
- Optimization: operational constraint logic in later phases.
- Security: identity separation, tokenization, access control, audit and trusted-computation boundary in later phases.
- Simulation: intervention simulation in later phases.

ML must not be coupled directly to the frontend. Synthetic-data generation must remain separate from prediction logic.

## Phase 0 data flow
Browser → Vite dev proxy → FastAPI `GET /health` → JSON `{ "status": "ok", "service": "FORTIFY" }`.

FastAPI startup initializes the SQLite prototype metadata table.

## Repository

```text
FORTIFY/
├── README.md
├── PROJECT_CONTEXT.md
├── PRODUCT_SPEC.md
├── ARCHITECTURE.md
├── DATA_SPEC.md
├── MODEL_SPEC.md
├── SECURITY_MODEL.md
├── ROADMAP.md
├── DEMO_SCENARIO.md
├── DECISIONS.md
├── TODO.md
├── .gitignore
├── .env.example
├── backend/
│   ├── requirements.txt
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── api/__init__.py
│   │   ├── api/routes/
│   │   ├── core/__init__.py
│   │   ├── core/config.py
│   │   ├── core/database.py
│   │   ├── models/__init__.py
│   │   ├── models/schemas.py
│   │   ├── services/__init__.py
│   │   ├── ml/__init__.py
│   │   ├── optimization/__init__.py
│   │   ├── security/__init__.py
│   │   └── simulation/__init__.py
│   └── tests/__init__.py
│   └── tests/test_health.py
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── components/
│       ├── pages/
│       ├── charts/
│       ├── simulator/
│       ├── services/
│       ├── types/
│       └── styles/
├── data/
│   ├── synthetic/
│   ├── schemas/
│   └── generated/
├── scripts/
└── docs/
    ├── research/
    └── diagrams/
```

## Phase 1 data flow

`CLI configuration → synthetic world generator → longitudinal event tables → schema validation → generated CSVs`

The generator is intentionally outside the ML layer. It creates operational conditions only. Phase 2 adds a separate feature-engineering layer under `backend/app/ml/`; it consumes the generated tables but does not train a model or calculate risk.

## Phase 2 feature-engineering flow

```text
Phase 1 event world
        ↓
Phase 2 feature engine (`backend/app/ml/feature_engineering.py`)
        ↓
person-day feature table (`data/generated/person_day_features.csv`)
        ↓
Phase 3 contextual baselines
```

The feature engine is deterministic, programmatically callable through `FeatureEngineer(...).build_features(...)`, and separate from model training. No risk score, forecast, recommendation, optimization, dashboard, RBAC, or TEE implementation is performed in Phase 2.

Phase 2 assumes the Phase 1 CSV inputs already exist under `data/generated/`; it does not regenerate them.


## Phase 3 baseline flow

```text
Phase 1 event world
        ↓
Phase 2 feature engine
        ↓
person-day feature table
        ↓
Phase 3 baseline engine (`backend/app/ml/baseline_engineering.py`)
        ├── Personal historical references (strictly prior days)
        ├── Cohort references (role + deployment_type, same-day, self-excluded)
        └── Operational references (unit_type + date, same-day, self-excluded)
        ↓
Phase 4 risk trajectory forecasting
```

Phase 3 remains a contextual-reference layer only. It does not create a risk score, prediction, diagnosis, recommendation, optimizer, or dashboard.


## Phase 4 predictive flow
Phase 1 event world
        ↓
Phase 2 engineered person-day features
        ↓
Phase 3 contextual baselines
        ↓
Phase 4 target construction + temporal split
        ↓
Preprocessing + LogisticRegression
        ↓
Predicted welfare-risk probability + LOW/MODERATE/ELEVATED presentation level
        ↓
Phase 5 explainability + uncertainty

Phase 4 excludes wellness-derived input columns from model training. Future wellness is used only to construct the supervised target; it is never included as an input at prediction time.

## Phase 7 data flow
Phase 1 operational events
→ Phase 2 person-day features
→ Phase 3 contextual baselines
→ Phase 4 prediction
→ Phase 5 risk decision
→ Phase 6 welfare-support recommendation
→ **Phase 7 operational feasibility / constraints**
→ Phase 8 security/privacy/TEE architecture

Phase 7 remains a deterministic policy/constraint layer. It does not create a new predictive risk model.

## Phase 8 security architecture

```text
Protected identity/data
        ↓
Identity separation + deterministic tokenization
        ↓
Purpose-bound authorization (RBAC)
        ↓
Prototype trusted computation boundary
        ↓
Analytics / inference using pseudonymous identifiers
        ↓
Authorized operational result
        ↓
Append-only audit log with integrity hash chain
```

Phase 8 adds reusable security controls under `backend/app/security/`. Identity-facing identifiers are pseudonymized before analytics-facing use; sensitive blobs can be encrypted with authenticated encryption; access is checked against both role and declared purpose; security-relevant actions can be recorded in a hash-chained audit log.

The prototype trusted-computation boundary is an application-process boundary only. It does not claim Intel TDX, AMD SEV-SNP, confidential-VM isolation, remote attestation, or hardware-backed key release. Those remain production architecture requirements.

Phase 8 does not modify Phase 4 prediction, Phase 5 risk decisions, Phase 6 welfare policy, or Phase 7 feasibility semantics.

## Phase 9 — Dashboard Integration

Phase 9 adds a read-only presentation layer on top of the Phase 5–8 decision pipeline:

```text
Phase 5 risk decision
        ↓
Phase 6 welfare intervention
        ↓
Phase 7 feasibility
        ↓
Phase 8 security boundary
        ↓
Phase 9 FastAPI dashboard endpoints
        ↓
React / Vite / TypeScript / Recharts dashboard
```

The dashboard uses aggregation endpoints rather than shipping the complete event/feature datasets to the browser. Individual welfare detail requires the existing Phase 8 welfare-support role and purpose. Aggregate dashboard access can use an authorized welfare or commander aggregate purpose.


## Phase 11 — Testing + hardening

Phase 11 hardening stays below the existing Phase 9/10 product flow and does not alter prediction, intervention policy, feasibility, security policy, or workflow semantics:

```text
Phase 9 dashboard
        ↓
Phase 10 human workflow
        ↓
Phase 11 hardening
  ├── persistence/index hardening
  ├── serialized workflow transitions
  ├── cache invalidation
  ├── artifact/privacy validation
  └── regression tests
        ↓
Phase 12 final demonstration preparation
```

## Phase 12 — Final demonstration preparation

Phase 12 adds a deterministic demonstration-preparation layer without changing the product runtime pipeline:

```text
Phase 9 dashboard
        ↓
Phase 10 human workflow
        ↓
Phase 11 hardened persistence / validation
        ↓
Phase 12 demo preparation
  ├── deterministic hero-case selection
  ├── 21-day operational/risk timeline
  ├── demonstration manifest
  └── readiness validation
        ↓
Final demonstration / human-led walkthrough
```

The preparation layer reads the existing Phase 5–10 artifacts and workflow state but does not mutate workflow state, rewrite earlier artifacts, expose raw wellness responses, or introduce new decision logic. The selected hero case is reproducibly chosen from existing synthetic data using a documented deterministic policy.

## Phase 13 — Operational Product Experience

Phase 13 evolves the Phase 9 presentation layer into the operational product experience defined by the UX blueprint without changing the prediction, intervention, feasibility, security, or workflow semantics.

```text
Phase 5 risk decision
        ↓
Phase 6 support recommendation
        ↓
Phase 7 feasibility
        ↓
Phase 8 security boundary
        ↓
Phase 9 API/dashboard foundation
        ↓
Phase 10 human workflow
        ↓
Phase 11 hardening
        ↓
Phase 12 deterministic demo preparation
        ↓
Phase 13 operational product experience
  ├── role-aware shell
  ├── attention queue
  ├── personnel / case discovery
  ├── aggregate unit context
  ├── trends
  ├── data provenance
  └── governance / system health
```

The frontend remains React + Vite + TypeScript + Recharts. Backend aggregation endpoints remain the transport boundary; raw event/feature datasets are not shipped to the browser. Individual personnel views continue to require the Phase 8 welfare-support role/purpose, while command views are aggregate-first.
## Phase 13.2 — Stitch Product Experience

**STATUS: COMPLETE**

Phase 13.2 implements the six-screen operational product experience from the supplied Stitch reference using the existing FORTIFY backend and security/workflow infrastructure. The screens are routed as Attention, dynamic Person Profile (`/person/:personId`), Units/Unit Command (`/units` and `/units/:unitId`), Data & Signals, Data Collection Management, and Governance/Security/Audit. Shared application chrome remains reusable across screens.

The Person Profile is fully data-driven and does not hard-code the Stitch hero example. Unit views remain aggregate-first and governance/data-management views respect the existing role/purpose authorization boundary. Raw wellness/self-report values are not emitted by the new UI.

The supplied Stitch HTML is treated as the visual and information-architecture reference; it is translated into React components rather than pasted into the application.

