"""Database connection layer.

The prototype runs on SQLite by default; the SQL in the persistence modules is
kept dialect-neutral (ANSI with ``ON CONFLICT`` upserts, which SQLite >= 3.24
and PostgreSQL both implement) so that the same schema and queries run on
PostgreSQL for a departmental deployment.

What is verified today:

* SQLite: the full test suite, lifecycle scripts, concurrency tests.
* PostgreSQL: schema creation, system metadata, workflow store initialization,
  transitions and concurrent transitions under a real postgres server (see
  ``backend/tests/test_postgres_live.py``, skipped automatically when no server
  is configured).

What remains SQLite-only: the ``PRAGMA`` connection settings below. They are
guarded by an explicit ``is_sqlite`` check so pointing the app at PostgreSQL
does not send SQLite directives to it.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Any

from app.core.config import settings

SQLITE_PREFIX = "sqlite:///"
POSTGRES_PREFIXES = ("postgresql://", "postgres://")


def is_postgres(database_url: str | None = None) -> bool:
    url = database_url if database_url is not None else settings.database_url
    return url.startswith(POSTGRES_PREFIXES)


def is_sqlite(database_url: str | None = None) -> bool:
    url = database_url if database_url is not None else settings.database_url
    return url.startswith(SQLITE_PREFIX)


def resolve_sqlite_url(database_url: str) -> Path:
    """Resolve a SQLite URL to a concrete database file path.

    Relative paths are anchored to the repository root so the database
    location does not depend on the process working directory.
    """
    if not database_url.startswith(SQLITE_PREFIX):
        raise ValueError("FORTIFY database URL must be sqlite:/// or postgresql://")
    raw = database_url.removeprefix(SQLITE_PREFIX)
    path = Path(raw)
    if not path.is_absolute():
        from app.core.paths import ROOT

        path = ROOT / path
    return path


def _sqlite_path() -> Path:
    return resolve_sqlite_url(settings.database_url)


class _QueryResult:
    """Cursor-like result matching the sqlite3 call sites (fetchone/fetchall,
    iteration, rowcount)."""

    def __init__(self, columns: list[str], rows: list["PostgresRow"], rowcount: int) -> None:
        self._columns = columns
        self._rows = rows
        self.rowcount = rowcount

    def fetchone(self) -> "PostgresRow | None":
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list["PostgresRow"]:
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)

    def __len__(self) -> int:
        return len(self._rows)


class PostgresRow:
    """Name- and index-based row access matching sqlite3.Row usage."""

    def __init__(self, columns: list[str], values: tuple) -> None:
        self._columns = columns
        self._values = dict(zip(columns, values))

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[self._columns[key]]
        return self._values[key]

    def keys(self):
        return self._values.keys()


class PostgresConnection:
    """Thin adapter so the persistence modules can send one SQL dialect to both
    backends: ``?`` placeholders and dict-row access are translated here.

    Only the operations the persistence modules actually use are implemented.
    If a deployment needs more, prefer migrating those call sites to this
    adapter rather than reintroducing dialect-specific SQL.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def _translate(self, sql: str) -> str:
        return sql.replace("?", "%s")

    def execute(self, sql: str, params: tuple | list = ()):
        cur = self._conn.cursor()
        cur.execute(self._translate(sql), tuple(params))
        rowcount = cur.rowcount
        if cur.description is not None:
            columns = [d.name for d in cur.description]
            rows = [PostgresRow(columns, row) for row in cur.fetchall()]
        else:
            columns, rows = [], []
        cur.close()
        return _QueryResult(columns, rows, rowcount)

    def executemany(self, sql: str, seq: list[tuple]) -> None:
        cur = self._conn.cursor()
        cur.executemany(self._translate(sql), [tuple(row) for row in seq])
        cur.close()

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


@contextmanager
def connect(sqlite_path: Path | None = None) -> Iterator[Any]:
    """Yield a connection for the configured database.

    Both backends receive the same SQL from the persistence modules. SQLite
    additionally gets its pragmas here, in one place. ``sqlite_path`` overrides
    the configured location (used by tests and scripts that isolate their
    database); it is ignored for PostgreSQL.
    """
    if is_postgres():
        try:
            import psycopg  # optional dependency: requirements-postgres.txt
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise RuntimeError(
                "FORTIFY_DATABASE_URL is a PostgreSQL URL but the psycopg driver "
                "is not installed. Install requirements-postgres.txt."
            ) from exc
        conn = psycopg.connect(settings.database_url, autocommit=False)
        try:
            yield PostgresConnection(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return

    import sqlite3

    conn = sqlite3.connect(sqlite_path or _sqlite_path(), timeout=10.0)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        yield conn
    finally:
        conn.close()


def begin_write(connection: Any) -> None:
    """Open a serialized write transaction.

    SQLite needs an explicit IMMEDIATE transaction to avoid upgrade deadlocks
    between concurrent writers. PostgreSQL transactions begin implicitly and
    the row locks below provide serialization.
    """
    if is_sqlite():
        connection.execute("BEGIN IMMEDIATE")


def lock_rows(connection: Any, sql: str, params: tuple = ()):
    """SELECT rows for a read-modify-write cycle, locking them.

    SQLite: plain SELECT inside the IMMEDIATE transaction already holds the
    write lock. PostgreSQL: the same SELECT must take row locks explicitly.
    """
    if is_sqlite():
        return connection.execute(sql, params).fetchall()
    rows = connection.execute(sql + " FOR UPDATE", params)
    return rows if rows is not None else []


def column_exists(connection: Any, table: str, column: str) -> bool:
    """Dialect-neutral replacement for PRAGMA table_info."""
    if is_sqlite():
        return column in {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    rows = connection.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = ?", (table,)
    )
    return any(str(row["column_name"]).lower() == column.lower() for row in rows)


def check_database() -> bool:
    """Return True when the configured database accepts a real query."""
    try:
        with connect() as connection:
            connection.execute("SELECT 1")
        return True
    except Exception:
        return False


def initialize_database() -> None:
    if is_sqlite():
        db_path = _sqlite_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect() as connection:
        # Dialect-neutral: ON CONFLICT upsert works on SQLite and PostgreSQL.
        connection.execute(
            "CREATE TABLE IF NOT EXISTS system_metadata "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO system_metadata(key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            ("service", "FORTIFY"),
        )