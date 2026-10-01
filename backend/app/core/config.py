import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # Relative SQLite paths are resolved against the repository root, not the
    # process working directory (see app.core.database.resolve_sqlite_url).
    database_url: str = os.getenv("FORTIFY_DATABASE_URL", "sqlite:///./backend/fortify.db")
    cors_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("FORTIFY_CORS_ORIGINS", "http://localhost:5173").split(",")
        if origin.strip()
    )


settings = Settings()
