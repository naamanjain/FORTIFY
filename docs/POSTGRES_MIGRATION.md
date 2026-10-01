# PostgreSQL migration path

**Status: documented future production requirement. FORTIFY's prototype runs
on SQLite by design, and this document does not pretend otherwise.**

## Why SQLite is correct for the prototype

The prototype must be reproducible from a clean clone with one command
(`python scripts/build_all.py`). SQLite gives that: no server, no credentials,
no ports, transactional, and a single file that CI can create and discard. The
demo dataset is small (hundreds of workflow rows), and every concurrent-write
path is already serialized (see *Concurrency* below). Replacing SQLite "to look
production-ready" would add a server dependency the demonstration does not
need and could not exercise in CI.

## Where the line is drawn

SQLite is appropriate **until** any of the following becomes true:

1. More than one backend replica needs to write workflow state.
2. The dataset outgrows single-host memory or disk-friendly CSV artifacts.
3. Point-in-time recovery, row-level security, or central backups are required
   by the department operating it.

At that point, deploy PostgreSQL and apply the changes in this document.

## What is already in place (verified)

- All persistence lives in exactly two modules: `app/core/database.py` and
  `app/services/workflow.py`. No route or ML module issues SQL.
- Every user-influenced value is a bound parameter (`?`). No string-formatted
  SQL touches request data.
- Transactions: workflow transitions run inside `BEGIN IMMEDIATE` and re-read
  the row inside the transaction, so a lost-update race is impossible on one
  host (regression-tested in `tests/test_security_regression.py` and
  `tests/test_phase11_hardening.py`).
- Indexes cover the read paths: pending queue ordering, per-item audit history,
  follow-up status scans, and feedback lookup.

## What must change for PostgreSQL

| SQLite construct | Where | PostgreSQL equivalent |
| --- | --- | --- |
| `PRAGMA foreign_keys` / `busy_timeout` | `core/database.py`, `services/workflow.py` | Remove; set `idle_in_transaction_session_timeout` and rely on server-side locking. |
| `INSERT OR IGNORE` | `services/workflow.py` (`ensure_workflow_items`) | `INSERT ... ON CONFLICT DO NOTHING` |
| `INSERT OR REPLACE` | `core/database.py`, unit backfill | `INSERT ... ON CONFLICT (key) DO UPDATE` (REPLACE deletes+reinserts, which breaks FKs) |
| `CREATE UNIQUE INDEX ... WHERE idempotency_key IS NOT NULL` | feedback idempotency | Supported natively (partial unique index) — no change. |
| `CREATE TEMP TABLE _personnel_units` | unit backfill | Use `ON CONFLICT` + a CTE, or a real staging table. |
| `BEGIN IMMEDIATE` | transition serialization | Not needed: `SELECT ... FOR UPDATE` inside the transaction gives the same guarantee. |
| `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` | `_ensure_column` migrations | Use a real migration tool (Alembic). Do not keep ad-hoc migration code. |
| `sqlite:///...` URL parsing | `resolve_sqlite_url` | Accept `postgresql://` URLs via SQLAlchemy Core or asyncpg; keep the two persistence modules as the only call sites. |

## Migration steps

1. Introduce SQLAlchemy Core with two URL backends (SQLite stays the default so
   CI and the demo remain reproducible).
2. Port the five workflow tables to Alembic migrations; keep the existing
   schema column-for-column (it is already normal and indexed).
3. Replace the four dialect-specific statements listed above.
4. Re-run the workflow lifecycle suite (`scripts/verify_workflow_lifecycle.py`)
   against both backends; the assertions are dialect-neutral today and must
   stay that way.
5. Load-test the transition path with two concurrent writers to replace
   `BEGIN IMMEDIATE` with `SELECT ... FOR UPDATE` confidently.

## What this project explicitly does NOT claim

- No PostgreSQL driver is shipped or configured.
- No dual-dialect test matrix exists.
- The concurrency guarantees stated above are single-host SQLite guarantees.
- Nothing in the README or dashboard should be read as "PostgreSQL ready" in
  the tested sense; it is *migration-path ready*.
