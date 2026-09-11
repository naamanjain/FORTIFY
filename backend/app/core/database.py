import sqlite3
from pathlib import Path

from app.core.config import settings


def _sqlite_path() -> Path:
    prefix = "sqlite:///"
    if not settings.database_url.startswith(prefix):
        raise ValueError("Phase 0 prototype database must use SQLite.")
    return Path(settings.database_url.removeprefix(prefix))


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
