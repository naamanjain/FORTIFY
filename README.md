# FORTIFY
### Force Operational Resilience & Timely Intervention Framework

[![CI](https://github.com/naamanjain/FORTIFY/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/naamanjain/FORTIFY/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Status](https://img.shields.io/badge/status-research%20prototype-orange)

**A privacy-conscious, human-in-the-loop welfare decision-support prototype for uniformed personnel.**

FORTIFY explores how authorised operational-pattern data can help surface meaningful changes for human welfare review. It connects data-quality checks, personal and contextual baselines, a ranked welfare signal, traceable contributing factors, feasible support options, case review, follow-up, and audit history.

> **Status and safety:** FORTIFY currently uses synthetic data only. Its model has not been validated on real personnel data, and the software is not approved or deployed for operational use. It is not a medical or psychiatric diagnostic system, a disciplinary tool, or an automated adverse-decision system.

FORTIFY was developed in response to Smart India Hackathon problem statement 26186. This repository is an independent prototype. Its publication does **not** imply endorsement, approval, partnership, or affiliation with the Ministry of Home Affairs, CRPF, or any government agency.

---

## Contents

- [Purpose](#purpose)
- [How it works](#how-it-works)
- [Capabilities](#capabilities)
- [Architecture](#architecture)
- [Progress and evidence](#progress-and-evidence)
- [Limitations](#limitations)
- [Run locally](#run-locally)
- [Run with Docker](#run-with-docker)
- [Tests and validation](#tests-and-validation)
- [Security and privacy](#security-and-privacy)
- [Path to an authorised pilot](#path-to-an-authorised-pilot)
- [Repository map](#repository-map)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [License](#license)

---

## Purpose

Uniformed personnel can work under demanding schedules, irregular duties, deployments, limited recovery time, transfers, and separation from family or support networks. Relevant information may be distributed across organisational systems, while a welfare concern may become visible only after someone raises it.

FORTIFY focuses on four practical questions:

1. Who may need a welfare check?
2. What has changed, compared with that person's usual pattern and relevant operational context?
3. Why is the signal worth reviewing?
4. What proportionate support and follow-up can an authorised human reasonably consider?

The aim is to support timely, contextual, explainable welfare review—not to label, diagnose, monitor indiscriminately, or replace human judgement.

## How it works

~~~text
Authorised operational data
          |
          v
Validation and data-quality checks
          |
          v
Temporal features + personal/contextual baselines
          |
          v
Ranking signal + meaningful-change / persistence policy
          |
          v
Traceable contributing factors
          |
          v
Welfare-support options + operational feasibility
          |
          v
Authorised human review and decision
          |
          v
Support -> feedback -> follow-up -> outcome
          |
          v
Auditable history
~~~

A model score is evidence for review, not a decision. The alert policy applies evidence, persistence, duplicate suppression, recovery logic, and a bounded case budget before items enter the human review queue. Workflow records are used to track human decisions, support, feedback, and follow-up.

### Product principles

- **Human judgement remains authoritative.** No automated diagnosis, punishment, or adverse personnel decision.
- **Signals must be explainable.** A displayed factor should trace to computed data, reference baseline, time window, and admission rule.
- **Context matters.** A difference from the global average is not by itself evidence of a welfare concern.
- **Purpose limitation matters.** Individual-level access is intended to require appropriate identity, role, purpose, and unit scope. Leadership visibility is aggregate-first.
- **Voluntary wellness remains voluntary.** Missing self-reports must never be treated as proof of distress.
- **Follow-through matters.** The workflow covers support, feedback, follow-up, outcomes, and audit—not just predictions.

## Capabilities

| Capability | Current prototype implementation |
|---|---|
| Synthetic longitudinal environment | Reproducible 500-personnel, 180-day demo world |
| Data pipeline | Validation, temporal features, personal/contextual baselines, generated model artifacts |
| Welfare signal | Logistic Regression is one ranking signal, not an autonomous decision-maker |
| Bounded review queue | Evidence and persistence policy, duplicate suppression, recovery logic, explicit budget suppressions |
| Explanation provenance | Contributing factors with computed values, references, windows, and admission rules |
| Support recommendations | Deterministic, non-punitive mapping with policy provenance |
| Operational feasibility | Recommendation feasibility against simulated operational constraints |
| Case workflow | Review, support planning/completion, feedback, follow-up, closure, and reopening |
| Unit-scoped access | Server-side scope checks and role/purpose regression tests using synthetic/test identities |
| Audit integrity | Hash-chained events with an HMAC-anchored head and tamper-detection tests |
| Data ingestion boundary | Opt-in, allow-listed schemas, path-contained writes, idempotency, and 16 MiB streaming cap |
| Operational checks | Health, readiness, version, metrics, redacted logs, data-quality and model-readiness checks |
| Reproducibility | Large generated data/model outputs are regenerated from source rather than committed |

### Interface areas

- **Attention:** cases requiring authorised review.
- **Person detail:** case, trend, baseline comparison, contributing factors, support and follow-up history.
- **Personnel and units:** role-appropriate personnel or aggregate operational views.
- **Trends and Data & Signals:** changes, source quality, and how signals are derived.
- **Reviews:** case decision workflow.
- **Follow-ups:** due, overdue, upcoming, and completed items.
- **Governance:** access-purpose and audit-oriented views.

## Architecture

~~~text
React 19 + TypeScript + Vite
          |
          | same-origin /api proxy
          v
FastAPI REST backend
  |-- dashboard and workflow services
  |-- authentication / authorization / audit
  |-- scoring, explanations, policy, feasibility
          |
          |-- generated CSV/model artifacts
          |-- SQLite demo workflow store
          |-- PostgreSQL application path, separately integration-tested
~~~

The offline data/model pipeline is separate from API request handling:

~~~text
scripts/build_all.py
  -> synthetic data generation
  -> feature engineering
  -> personal/contextual baselines
  -> model training
  -> calibrated risk decisions
  -> bounded review queue
  -> explanations and recommendations
  -> feasibility
  -> demo preparation
~~~

**Technology**
- Frontend: React 19, TypeScript, Vite, Recharts.
- Backend: Python, FastAPI, Pydantic.
- Data and ML: Pandas, NumPy, SciPy, scikit-learn.
- Persistence: SQLite for the reproducible demo; application-side PostgreSQL support.
- Operations: Docker, nginx, GitHub Actions, and Kubernetes reference manifests.

## Progress and evidence

The latest inspected public GitHub Actions run, for commit bc5df1b, completed successfully across five jobs: secret/history scan, Docker build, frontend build, backend verification, and PostgreSQL integration.

The maintainer's local verification report dated 19 October 2026 recorded:

| Check | Reported result |
|---|---|
| Backend test suite | 328 passed, 4 skipped on Windows; skip reasons documented |
| Standalone validators | 14/14 passed |
| API acceptance workflow | 14/14 passed |
| Case lifecycle workflow | 20/20 passed |
| Model validity probes | Leakage, label-leakage, and contamination probes passed |
| SQLite backup/restore drill | 8/8 checks passed |
| Disposable PostgreSQL 16 integration | 3/3 tests passed locally |
| Frontend | Dependency install, audit, TypeScript check, and production build passed locally |
| Docker Compose | Build, health, proxy, and upload-limit checks passed locally |
| Kubernetes | No live cluster deployment was verified |

These results are dated engineering evidence, not a guarantee that every contributor environment will reproduce the same timings or state. See [Production Readiness](docs/PRODUCTION_READINESS.md) for evidence and limitations.

### Model evidence: what the results mean

The default demo uses the **legacy synthetic generator**. Its target construction has a direct same-day relationship with operational features, so metrics from this world cannot establish real-world predictive effectiveness.

Reported top-of-queue precision on the shipped legacy demo world:

| Strategy | Top 1% | Top 2% | Top 5% | Top 10% |
|---|---:|---:|---:|---:|
| Simple operational rule | 0.745 | 0.784 | 0.706 | 0.647 |
| Unfitted temporal score | 0.804 | 0.784 | 0.773 | 0.741 |
| Logistic Regression | 0.725 | 0.716 | 0.706 | 0.645 |
| L2 Logistic Regression | 0.706 | 0.667 | 0.682 | 0.675 |

At the deployed thresholded operating point, the reported model F1 was 0.322 versus 0.614 for the simple rule. A more permissive threshold raised the model F1 to around 0.633 but required flagging roughly 54% of person-days—an impractical review burden.

**Architecture decision: Option B.** The model stays as one ranking signal within a bounded, human-owned review queue. It is not demonstrated to be consistently superior to simple rules, and no real-world personnel outcome claim is made. The latent-state generator is benchmark-only in this release and is not the source of the prepared demo artifacts.

Detailed methods and caveats are in [Model Lineage](docs/MODEL_LINEAGE.md).

## Limitations

FORTIFY is a **research and demonstration prototype**, not an operationally approved government system.

- **Synthetic data only.** No real personnel, departmental, or wellness records are included.
- **No real-world predictive validation.** Synthetic metrics do not establish clinical, occupational, or operational effectiveness.
- **Demo authentication is not real authentication.** Default demo mode trusts caller-supplied role and purpose headers. Anyone who can reach a demo instance may be able to assert a role. It is intended for local synthetic-data demos only.
- **OIDC adapter is not an IdP deployment.** JWT/JWKS validation has been tested with locally generated keys; a real departmental identity provider, provisioning, MFA/session/logout lifecycle, and approved organisational claim policy have not been verified end to end.
- **Unit-scope semantics require institutional agreement.** The mechanism is tested with synthetic/test identities. Real roster data and transfer, multi-unit, and acting-role rules need an authorised policy owner.
- **PostgreSQL is an application path, not a managed production service.** Disposable PostgreSQL tests passed; departmental hosting, failover, point-in-time recovery, and operations are not in place.
- **Backups are not yet production operations.** A scripted SQLite backup/restore drill exists; scheduled/off-site/immutable backups, retention, measured RPO/RTO, and a production PostgreSQL restore rehearsal remain outstanding.
- **Kubernetes is reference deployment material.** No real cluster deployment/soak test has been verified.
- **No TEE, HSM, or remote attestation.** Do not infer hardware-backed security from the audit-chain or encryption features.
- **Explanations are associative, not causal.** They describe operational factors associated with a higher model signal, not why a person feels a particular way.

## Run locally

These instructions assume Windows PowerShell and VS Code. The full command guide is [RUN_FORTIFY_IN_VSCODE.txt](RUN_FORTIFY_IN_VSCODE.txt).

### Prerequisites

- Python 3.13; backend pins are in backend/requirements.txt.
- Node.js 24 and npm.
- Git.
- Docker Desktop with Compose v2 is optional.

### First-time setup

Open the **repository root** in VS Code—the directory containing README.md, backend/, frontend/, and scripts/.

Terminal 1, PowerShell at the repository root:

~~~powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
python scripts/build_all.py
~~~

The generation step is required on a fresh clone. It takes several minutes and creates several hundred MB of regenerable, ignored output. Do not rerun it every time you start the app; rebuild only when outputs are missing or you intentionally regenerate the demo world.

Start the backend in Terminal 1, from the repository root:

~~~powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
~~~

Terminal 2, starting at the repository root:

~~~powershell
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
~~~

Open **http://127.0.0.1:5173**.

### Verify backend status

In a third terminal:

~~~powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
Invoke-RestMethod http://127.0.0.1:8000/version
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/metrics
~~~

- /health reports process liveness.
- /ready checks required database, artifacts, data quality, and model readiness.
- /version identifies the build.
- /metrics exposes operational counters without intended person-level welfare content.

If /ready returns 503 after a fresh clone, inspect the response and confirm the pipeline completed successfully.

### Everyday startup

After first-time setup, use two terminals; do not rebuild the pipeline unless needed.

Backend, from repository root:

~~~powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
~~~

Frontend, from repository root:

~~~powershell
cd frontend
npm run dev -- --host 127.0.0.1
~~~

Stop each process with Ctrl+C. If PowerShell blocks virtual-environment activation, run Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass in that terminal only, then activate again.

## Run with Docker

~~~bash
docker compose up --build
~~~

Open http://127.0.0.1:5173. Compose publishes on loopback by default. The pipeline service regenerates artifacts into volumes; container generation may take longer than host-native generation.

Stop the stack:

~~~bash
docker compose down
~~~

Use docker compose down -v only if you intentionally want to delete the project's named volumes and reset containerised demo state. Do not expose the Compose demo to an untrusted network or use it with real personnel data.

## Tests and validation

Generate demo artifacts first:

~~~powershell
python scripts/build_all.py
~~~

Run the backend tests from the repository root with the project virtual environment active:

~~~powershell
python -m pytest -q
~~~

Model validity, benchmark, alert-burden, and backup/restore checks:

~~~powershell
python scripts/validate_model_validity.py
python scripts/benchmark_operational.py
python scripts/simulate_alert_fatigue.py
python scripts/backup_restore_drill.py
~~~

The 14 pipeline/product validators:

~~~powershell
python scripts/validate_synthetic_data.py --output data/generated --personnel 500 --days 180
python scripts/validate_features.py --input data/generated/person_day_features.csv --personnel 500 --days 180
python scripts/validate_baselines.py --input data/generated/person_day_features_baseline.csv
python scripts/validate_model.py
python scripts/validate_phase5_risk_layer.py
python scripts/validate_interventions.py --input data/generated/intervention_recommendations.csv --report data/generated/intervention_generation_report.json
python scripts/validate_feasibility.py --expected-rows 90000
python scripts/validate_security.py
python scripts/validate_workflow.py
python scripts/validate_dashboard.py
python scripts/validate_demo.py
python scripts/validate_hardening.py
python scripts/validate_product_experience.py
python scripts/validate_stitch_product.py
~~~

For acceptance and lifecycle checks, keep the backend running and use another terminal:

~~~powershell
python scripts/verify_acceptance.py
python scripts/verify_workflow_lifecycle.py
~~~

These scripts use the live API by default at http://localhost:8000. Check their current help/configuration if using another port or server.

The test suite exercises workflow transitions and can change the local demo store. Use an isolated runtime/database or rebuild and re-prepare the demo when you need a pristine presentation.

## Security and privacy

Security features implemented and covered by prototype tests include:
- central role × purpose authorisation;
- server-side unit-scope checks for individual-level reads and mutations;
- aggregate-first command views;
- privacy-surface regression tests;
- encrypted-field and pseudonymisation utilities;
- hash-chained audit events with an HMAC-anchored head;
- audit records for important workflow actions and denials;
- structured, redacted logging;
- input validation, rate/body limits, path-contained ingestion writes, idempotency checks, and fail-safe error handling;
- production authentication mode that fails closed when OIDC configuration is incomplete.

**These controls do not remove the demo-authentication limitation.** Default demo mode trusts client-supplied role and purpose headers. Loopback binding reduces network exposure but does not verify identity. Do not expose the demo to untrusted networks and do not use it with real personnel records.

Ingestion is opt-in and validation-only; no live departmental feed is connected. The batch limit is 16 MiB.

The audit HMAC key is local-demo infrastructure unless deliberately provisioned and managed through an external secret-management process. Do not commit keys, production credentials, local databases, generated data, runtime audit files, or environment files.

## Path to an authorised pilot

Moving from prototype to a government evaluation or pilot requires separate technical, institutional, and governance work:

1. **Sponsor and policy owner:** define purpose, decision rights, access rules, escalation, retention, and prohibited use.
2. **Real identity integration:** connect an authorised OIDC/SSO provider and verify claims, roles, unit scopes, provisioning, revocation, and session lifecycle.
3. **Approved data contract:** define authorised sources, schemas, provenance, freshness, validation, and failure handling.
4. **Privacy/security assessment:** review access boundaries, audit-key management, secrets, threat model, encryption, logs, retention, incident response, and independent security testing.
5. **Operational hosting:** managed database, tested backups and recovery, monitoring/alerting, capacity, deployment controls, rollback, and continuity requirements.
6. **Prospective validation:** use authorised data under proper approvals. Compare against simple baselines at realistic review capacity, measure alert burden and context stability, and define stop criteria before a supervised pilot.
7. **Human-factors evaluation:** check whether the interface supports timely, proportionate support without stigma, over-reliance, punitive interpretation, or alert fatigue.

No government deployment, official approval, real-world effectiveness, or procurement status is claimed. A technical evaluation or pilot must be authorised by the relevant institution.

See [Production Readiness](docs/PRODUCTION_READINESS.md), [Security Model](SECURITY_MODEL.md), [Model Lineage](docs/MODEL_LINEAGE.md), and [Backup/Recovery](docs/BACKUP_RECOVERY.md).

## Repository map

~~~text
FORTIFY/
├── backend/
│   ├── app/                    # FastAPI, services, security, ML and persistence
│   ├── tests/                  # Unit, integration, privacy and regression tests
│   ├── requirements.txt        # Pinned demo/backend dependencies
│   └── requirements-postgres.txt
├── frontend/                   # React, TypeScript, Vite, nginx
├── scripts/                    # Pipeline, validation, benchmark and demo tools
├── data/
│   ├── schemas/                # Tracked schemas
│   ├── generated/              # Regenerable, ignored output
│   └── runtime/                # Local runtime state; never commit
├── artifacts/                  # Generated models/reports/demo data; ignored
├── deploy/k8s/                 # Kubernetes reference manifests
├── docs/                       # Architecture, security, model lineage, readiness, runbooks
├── .github/workflows/ci.yml    # Automated quality gates
├── docker-compose.yml
├── RUN_FORTIFY_IN_VSCODE.txt
└── README.md
~~~

## Documentation

- [Architecture](ARCHITECTURE.md)
- [Product specification](PRODUCT_SPEC.md)
- [Model specification](MODEL_SPEC.md)
- [Data specification](DATA_SPEC.md)
- [Security model](SECURITY_MODEL.md)
- [Model lineage and benchmark](docs/MODEL_LINEAGE.md)
- [Production readiness matrix](docs/PRODUCTION_READINESS.md)
- [PostgreSQL path and migration notes](docs/POSTGRES_MIGRATION.md)
- [Backup and recovery](docs/BACKUP_RECOVERY.md)
- [Demo runbook](docs/DEMO_RUNBOOK.md)
- [VS Code run commands](RUN_FORTIFY_IN_VSCODE.txt)
- [Kubernetes reference deployment](deploy/k8s/README.md)

## Contributing

Contributions and reviews are welcome. Before opening a pull request:

1. Read the architecture, security model, and relevant specification.
2. Keep generated data, runtime files, local databases, caches, build output, secrets and private data out of Git.
3. Add tests for behaviour changes, particularly authorization, privacy, audit integrity, data quality, and workflow transitions.
4. Run the relevant validators and tests.
5. Describe what was actually executed; do not claim a check passed if it was skipped or only reviewed statically.
6. Preserve the non-punitive, human-in-the-loop welfare purpose. Do not add diagnostic claims, automatic adverse decisions, or unsupported government-policy claims.

## License

FORTIFY is distributed under the [MIT License](LICENSE). The software is provided “as is”, without warranty. A permissive software license does not confer permission to access or process government or personnel data; any real deployment requires the appropriate authorisation and governance.
