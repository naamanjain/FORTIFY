# PostgreSQL path

**Status: implemented application-side path, not a production deployment.**
SQLite remains the default and the only backend exercised by the full local
test run. PostgreSQL support is real code, not a plan:
`FORTIFY_DATABASE_URL` accepts `postgresql://`, `backend/requirements-postgres.txt`
ships the driver/pool, and the opt-in live test was executed on 2026-10-19
against a disposable `postgres:16` container (3 passed). Nothing here claims a
tested departmental deployment.

## Why SQLite is still the default

The prototype must be reproducible from a clean clone with one command
(`python scripts/build_all.py`). SQLite gives that: no server, no credentials,
no ports, transactional, and a single file that CI can create and discard. The
demo dataset is small (tens of thousands of workflow rows), and every
concurrent-write path is serialized (see *Concurrency* below). Requiring a
database server for the demonstration would add infrastructure the demo does
not need.

## Where the line is drawn

SQLite is appropriate **until** any of the following becomes true:

1. More than one backend replica needs to write workflow state.
2. The dataset outgrows single-host memory or disk-friendly CSV artifacts.
3. Point-in-time recovery, row-level security, or central backups are required
   by the department operating it.

At that point, deploy PostgreSQL using the application path below, and add the
operational work listed under *What remains*.

## Implemented (application side)

| Concern | Implementation |
| --- | --- |
| URL handling | `app/core/database.py` accepts `sqlite:///` and `postgresql://`/`postgres://`; relative SQLite paths resolve against the repository root. |
| Driver and pooling | `backend/requirements-postgres.txt` (`psycopg[binary]`, `psycopg-pool`); one lazily opened `ConnectionPool` per process with reconnect-on-checkout. |
| SQL dialect | Persistence modules use bound `?` parameters; the PostgreSQL adapter translates placeholders. Upserts use `ON CONFLICT`; there are no `INSERT OR REPLACE`, `INSERT OR IGNORE`, or temporary-table statements left. |
| Schema | `app/core/migrations.py` is a versioned, recorded, idempotent migration runner shared verbatim by both backends. Migration 1 is additive; `ALTER TABLE ... ADD COLUMN` statements are guarded by a live `column_exists` check. |
| Partial unique index | `uq_workflow_feedback_idem ON workflow_feedback(idempotency_key) WHERE idempotency_key IS NOT NULL` is supported natively by both engines. |
| Transactions | `begin_write()` issues `BEGIN IMMEDIATE` on SQLite only. On PostgreSQL, `lock_rows()` appends `FOR UPDATE`, so the state read and the write are one serialized cycle. |
| Type/row access | `PostgresConnection`/`PostgresRow` preserve the sqlite3-style `fetchone()`/`fetchall()`/name access the persistence modules already use. |

## Verification status

- **SQLite:** full local suite, lifecycle scripts, acceptance API, and the
  scripted backup/restore drill (see `docs/PRODUCTION_READINESS.md`).
- **PostgreSQL, live:** `backend/tests/test_postgres_live.py` drops and
  recreates the `public` schema on a **disposable** database, then checks
  migrations, the partial unique index, a real workflow transition, and two
  concurrent transitions racing on the same row (exactly one must win, and
  exactly one transition event must be written). Executed on 2026-10-19 against
  a disposable `postgres:16` container started with Docker: **3 passed, exit 0**.
  The `postgres-integration` job in `.github/workflows/ci.yml` runs the same
  module against a fresh `postgres:16` service container; that CI job itself
  was not executed by GitHub Actions in this run.
- **Default suite:** the module is skipped when `FORTIFY_TEST_POSTGRES_URL` is
  unset, which is why the normal Windows local run reports 332 collected:
  328 passed, 4 skipped (the 3 PostgreSQL tests plus the symlink-containment
  test, skipped only where Windows denies symlink creation). The PostgreSQL
  skips were separately executed against the disposable server and passed.
  The full 328-test suite was not re-run with every test pointed at PostgreSQL;
  the live module covers the store contract, not every dashboard/workflow test.

## What remains

| Gap | Why it matters |
| --- | --- |
| Alembic or an equivalent migration tool | The in-repo runner is forward-only and deliberately small. It has no downgrade path; a destructive migration must not ship without a tested rollback. |
| Connection and transaction tuning | `idle_in_transaction_session_timeout`, statement timeouts, pool sizing under departmental load, and query-plan review are not measured. |
| Row-level security | Not implemented; authorization is application-enforced. |
| Backups, PITR, replication, failover | Application code cannot supply these. See `docs/BACKUP_RECOVERY.md`; the backup drill's PostgreSQL mode shells out to Docker and is not production tooling. |
| Multi-replica testing | The row-lock test covers one racing pair, not a departmental load profile. |
| Full dual-dialect suite | The live module covers the store contract, not every dashboard/workflow test. |

## What this project explicitly does NOT claim

- No PostgreSQL deployment is running or configured by this repository.
- Live PostgreSQL coverage is limited to the disposable integration module; it
  is not a departmental deployment or a full dual-dialect suite.
- PostgreSQL performance, failover, backup, and multi-replica behaviour are
  unmeasured.
- A green default test run is not evidence about PostgreSQL; only the live
  module is.
