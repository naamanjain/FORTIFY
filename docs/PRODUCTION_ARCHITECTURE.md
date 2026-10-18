# FORTIFY production architecture

**Read this as an engineering specification of intended topology — not a
description of something already running.** The demonstration deployment
described in the README is not production, and nothing in this repository
should be read as claiming otherwise.

## Deployment tiers

| Tier | Purpose | Database | Auth | Data |
|---|---|---|---|---|
| **DEMO** (what the repository runs) | Evaluation, demonstration, development | SQLite file | `FORTIFY_AUTH_MODE=demo` — header trust, explicitly unauthenticated | Deterministic synthetic world, regenerated from seed 42 |
| **STAGING** | Pre-production rehearsal of the real topology | PostgreSQL (department-managed or container) | `FORTIFY_AUTH_MODE=production` with a **test** IdP realm | Synthetic or anonymized data through the ingestion boundary |
| **PRODUCTION** | Departmental operation | PostgreSQL with backups per `BACKUP_RECOVERY.md` | `FORTIFY_AUTH_MODE=production` with the department IdP | Authorised operational feeds via the ingestion boundary only |

Every promotion path (DEMO → STAGING → PRODUCTION) requires the same three
things: real authentication configured, PostgreSQL verified (including the
backup/restore drill), and data admitted through the ingestion boundary. A
tier that skips any of the three is DEMO regardless of what it is called.

## Intended production topology

```
                     departmental network
   ┌────────────┐        ┌─────────────────────────────┐
   │  browser    │──────▶│ ingress / reverse proxy      │  TLS termination,
   │  (officer)  │        │ (nginx / departmental GW)   │  rate limits, body caps
   └────────────┘        └──────────────┬──────────────┘
                                        │
                        ┌───────────────▼────────────────┐
                        │ FORTIFY API (FastAPI, replicas) │  auth: OIDC bearer
                        │ • dashboard (read-only)         │  tokens validated
                        │ • review queue (alert policy)   │  against issuer/JWKS
                        │ • workflow (human transitions)  │
                        │ • ingestion endpoint (opt-in)   │
                        └───┬──────────┬──────────┬───────┘
                            │          │          │
              ┌─────────────▼───┐  ┌───▼────────┐ ┌▼─────────────────────┐
              │ PostgreSQL       │  │ artifacts  │ │ audit + observability │
              │ workflow state,  │  │ model +    │ │ append-only JSONL     │
              │ migrations,      │  │ queue CSVs │ │ (anchored head; ship  │
              │ backups          │  │ (RO mount) │ │ segments off-host)    │
              └──────────────────┘  └────────────┘ └───────────────────────┘
                            ▲
              ┌─────────────┴──────────────┐
              │ ingestion boundary          │  authorised feeds only;
              │ validate → stage → pipeline │  invalid batches never become
              └─────────────────────────────┘  welfare signals
```

Properties that are architectural, not configurable:

1. **Authentication happens before authorization.** The API accepts verified
   identity claims only; in production mode there is no code path that turns
   request headers into a principal.
2. **The model is one ranking component.** The value chain is operational
   data → change vs personal/contextual baseline → ranked signal →
   explanation → feasible welfare option → human review → support →
   follow-up → outcome → audit. Removing the model degrades ranking, not
   governance.
3. **Scores never create work directly.** The alert policy (persistence,
   suppression, daily budget) sits between scores and cases; humans own every
   case transition.
4. **Invalid data never becomes welfare evidence.** The ingestion boundary is
   validation-only; the deterministic pipeline is the only path from records
   to features and scores.
5. **Audit is append-only and anchored.** Log and anchor are preserved as a
   pair and shipped off-host; the application refuses to append to a damaged
   log.

## Component responsibilities in production

- **Ingress**: TLS termination, request-size caps, edge rate limiting,
  access logs. The application's own rate limiter (`FORTIFY_RATE_LIMIT`) is a
  second layer, not the primary one.
- **API replicas**: stateless apart from the workflow database; horizontal
  scaling requires PostgreSQL (documented in `POSTGRES_MIGRATION.md`).
- **Pipeline**: batch process (container `pipeline` service / k8s Job)
  regenerating features, model artifacts and the review queue from staged
  data; not request-serving.
- **Model artifacts**: read-only mounts; versioned by the model registry
  (explicit promotion, never automatic).
- **PostgreSQL**: single source of workflow truth; pooling via
  `psycopg_pool`; migrations via the versioned runner in
  `app/core/migrations.py`.
- **Object storage**: for audit log segments and database backups, with
  versioning and retention set by departmental policy (not defined in this
  repository).

## What is intentionally absent

- No service mesh, multi-cluster, or auto-failover story: none is needed at
  this scale and none has been tested.
- No analytics warehouse, BI layer, or outcome-measurement pipeline beyond
  the workflow feedback that already exists.
- No promise of regulatory compliance: privacy (GDPR-style) and records
  obligations are departmental legal questions this repository cannot answer.
