# Production readiness matrix

Status as of 2026-10-01. "Verified" means the claim was exercised by an
automated test or a live deployment check in this repository — not read from a
document. Everything in the **Remaining work** column is real, unscheduled
work; nothing here should be read as a roadmap claim of completion.

Legend: ✅ verified · ⚠️ partially verified (limitation stated) · ❌ not implemented

| Area | Current state | Verified? | Evidence | Remaining work | Production blocker? |
|---|---|---|---|---|---|
| **Authentication** | Demo header-trust authenticator, isolated behind `Authenticator`; `FORTIFY_AUTH_MODE=production` fails closed at startup | ✅ | `test_auth_modes.py` (production refuses to boot; unknown mode refuses; runtime replacement seam works) | OIDC/OAuth2 implementation against the department IdP; token validation; session lifecycle | **Yes** |
| **Authorization** | Role × purpose matrix enforced at one choke point; view classes (aggregate/welfare/audit/infrastructure); object-level checks on every route | ✅ | `test_security_regression.py`, `test_phase9_dashboard.py` (purpose-limitation, mismatched-purpose, unknown-role tests) | Per-officer unit scoping (officers currently see the whole roster within their purpose) | Yes for multi-unit deployments |
| **Database** | SQLite (demo) + PostgreSQL path running the same dialect-neutral SQL; schema, constraints, transitions, concurrent-write serialization verified on a real PostgreSQL 16 server | ✅ | Live container verification (transitions, race serialization, unique indexes in PG catalog); `docs/POSTGRES_MIGRATION.md` | Alembic migrations (ad-hoc `_ensure_column` remains); connection pooling; production hosting | **Yes** for multi-replica |
| **Storage** | Generated CSV artifacts + audit JSONL on local/volume storage; k8s PVC manifest | ⚠️ | Compose stack verified end-to-end; k8s validated offline only (no cluster) | Object storage with versioning; artifact lifecycle management | Yes for production |
| **ML** | Calibrated logistic regression as a *ranking signal*; rule + temporal-score baselines benchmarked; validity probes pass; honest capability limits documented | ✅ | `scripts/validate_model_validity.py`, `scripts/benchmark_operational.py`, `docs/MODEL_LINEAGE.md` §5 | Real-data validation; prospective monitoring; drift-response runbook | Model itself is not a blocker (system designed for model failure) — real-data validation **is**, before any operational use |
| **Data pipeline** | Deterministic, seed-pinned, regenerable from a clean clone; alert policy bounds case creation | ✅ | Clean-clone verification; `validate_*` suite; CI regenerates | Ingestion connector hardening (boundary module exists; no live departmental feed) | Yes |
| **Monitoring** | `/health`, `/ready` (db+artifacts+data quality), `/metrics`, `/version`; model/pipeline version, data freshness, score-drift indicator on system-health; JSON logs with redaction | ✅ | `test_health.py`, `test_resilience.py`, live endpoint checks | Central log/metric aggregation; alerting rules; dashboards | Yes for production |
| **Audit** | Append-only hash chain with HMAC-anchored head; truncation and rewrite detection; fail-closed on damaged log; redacted reads | ✅ | `test_security_regression.py::TestAuditTamperEvidence` (truncate, full-rewrite, anchor-delete, key-forgery, corrupt-tail) | Externally anchored head (remote notary/WORM store); chain rotation | Yes for production evidentiary use |
| **Deployment** | Docker images (non-root, healthchecks), compose stack, k8s manifests with probes/securityContext/resources/PVC | ⚠️ | Compose verified live (healthy, uid 10001, acceptance 14/14 through nginx); k8s manifests parsed + cross-checked offline | Real cluster soak test; ingress TLS; image signing | No (prototype); yes for production |
| **Backups** | Requirements documented; nothing automated | ❌ | `docs/BACKUP_RECOVERY.md` | Automated backups, restores rehearsed, recovery time objectives met | **Yes** |
| **Secrets** | No secrets in image or repo; audit anchor key from env or generated file with documented limits | ⚠️ | Secret scan in CI; `FORTIFY_AUDIT_HMAC_KEY` documented | Secret manager integration; per-environment key ceremony | **Yes** |
| **Privacy** | Purpose limitation enforced; wellness fields excluded from features and API; audit reads redact personnel ids; log redaction | ✅ | Contract sweep test (no wellness field in any payload); fidelity tests | Data-protection impact assessment; retention schedule; legal review | **Yes** |
| **Governance** | Non-punitive recommendation vocabulary with forbidden-terms guard; human-owned case lifecycle; provenance chains | ✅ | `validate_interventions.py`, provenance tests | Departmental policy sign-off; policy version register | Yes for production |
| **Performance** | Dashboard artifact cache; bounded queue endpoints; request metrics | ⚠️ | Live smoke; `http_request_seconds` metric | Load testing at departmental scale; PG query plans | Yes for production |
| **Resilience** | Fail-safe startup; 503-with-remedy on missing/corrupt artifacts; corrupt audit log refuses appends; rate limiting; optimistic concurrency | ✅ | `test_resilience.py` (10 cases), `test_security_regression.py` | Chaos/drill exercises; multi-replica session strategy | Yes for production |

Summary: the prototype is **defensible as a demonstration and as an
engineering artifact**. The production blockers are exactly the ones stated:
real authentication, a production database deployment, backups, secret
management, and — before any operational welfare use — real-data validation
and governance sign-off.
