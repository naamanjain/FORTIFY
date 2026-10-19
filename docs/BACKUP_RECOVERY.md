# Backup and recovery requirements

**Status: production requirements plus a scripted SQLite restore drill.
Automated backups, scheduling, off-site/immutable copies, retention, and
production PostgreSQL recovery are NOT implemented, and no RPO/RTO is
claimed.** The prototype stores state in three places; a departmental
deployment must protect all three.

## What exists today (prototype)

| Store | Contents | Loss impact |
|---|---|---|
| `data/generated/` | Regenerable datasets, models, queue artifacts | None — `scripts/build_all.py` reproduces the decisions at seed 42 |
| Workflow database | Case states, support events, feedback, follow-ups, materialization epoch | Loss of human workflow history — **not regenerable** |
| Audit log + anchor | Hash-chained governance evidence and its signed anchor | Loss of evidentiary history — **not regenerable** |

Only the second and third need backup.

### Scripted SQLite drill (exercise, not an operational backup)

`scripts/backup_restore_drill.py` performs, against the configured database:
consistent backup, a real mutation, restore from that backup, then verification
of row counts, workflow history, constraint integrity, and `AuditLog.verify()`
against the restored anchor. It prints timings and writes
`artifacts/backup_restore/drill_report.json`.

The drill passed **8/8 checks on SQLite** in this working tree. That is
evidence the procedure works; it is **not** a scheduled backup, an off-site
copy, an RPO/RTO measurement, or a PostgreSQL restore rehearsal. The script has
a PostgreSQL mode, but it shells out to `docker exec`/`pg_dump`/`psql` and was
not executed in this run; no PostgreSQL restore rehearsal is claimed. The
disposable live PostgreSQL test (`test_postgres_live.py`) proves the store
contract, not backup/restore.

## Production requirements (PostgreSQL deployment)

1. **Database backups** — continuous archiving (WAL shipping) with nightly
   base backups, or managed-service equivalents. RPO ≤ 15 min for the
   workflow database; the audit log may warrant tighter.
2. **Audit log** — appended on every decision; ship each closed file segment
   to versioned object storage (WORM/retention lock where available) **and**
   store the anchor file with it. An anchor without its log (or the reverse)
   fails verification by design — they must be preserved as a pair.
3. **Retention** — welfare workflow records and audit evidence are governance
   records; retention follows departmental policy, which does not exist yet.
   Define it before go-live; do not inherit this prototype's behaviour.
4. **Recovery testing** — a rehearsed, timed restore drill (documented RTO),
   run at least quarterly: restore to a clean host, run
   `AuditLog.verify()` (must pass against the restored anchor), and confirm
   case-state counts against the pre-failure snapshot.
5. **Migration rollback** — schema changes are migrations; each must ship
   with a tested downgrade path before it ships at all. The current
   `app/core/migrations.py` runner is forward-only and migration 1 is
   additive; there is no downgrade path today. The moment a migration
   destroys or reshapes data, rollback must be tested, not assumed.
6. **Object-storage protection** — versioning enabled; deletion requires
   break-glass approval; backups of the backups are out of scope until a
   second region is real.

## What must NOT be claimed

- **No RPO/RTO is met today.** The SQLite drill is a procedure test, not a
  scheduled backup or a production recovery rehearsal.
- **No PostgreSQL restore drill has been run here.** The PostgreSQL mode of the
  drill requires Docker (`pg_dump`/`psql`) and was not executed in this run.
- The audit chain's tamper evidence protects against *tampering*; it is not a
  backup. Losing the log and its anchor loses the evidence chain.
- `build_all.py` regenerates synthetic data, never workflow history.
