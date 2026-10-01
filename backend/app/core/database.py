import sqlite3
from pathlib import Path

from app.core.config import settings

SQLITE_PREFIX = "sqlite:///"


def resolve_sqlite_url(database_url: str) -> Path:
    """Resolve a SQLite URL to a concrete database file path.

    Relative paths are anchored to the repository root so the database
    location does not depend on the process working directory.
    """
    if not database_url.startswith(SQLITE_PREFIX):
        raise ValueError("FORTIFY prototype database must use SQLite (sqlite:/// URL).")
    raw = database_url.removeprefix(SQLITE_PREFIX)
    path = Path(raw)
    if not path.is_absolute():
        from app.core.paths import ROOT

        path = ROOT / path
    return path


def _sqlite_path() -> Path:
    return resolve_sqlite_url(settings.database_url)


def check_database() -> bool:
    """Return True when the configured database accepts a real query."""
    try:
        with sqlite3.connect(_sqlite_path(), timeout=10.0) as connection:
            connection.execute("SELECT 1")
        return True
    except sqlite3.Error:
        return False


def initialize_database() -> None:
    db_path = _sqlite_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path, timeout=10.0) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS system_metadata "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT OR REPLACE INTO system_metadata(key, value) VALUES (?, ?)",
            ("service", "FORTIFY"),
        )
        connection.commit()
