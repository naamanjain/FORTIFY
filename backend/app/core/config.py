import os
from dataclasses import dataclass

# Demonstration-only sentinel for FORTIFY_DEMO_UNIT_SCOPE. Never honoured for a
# verified identity, and never honoured outside demo auth mode.
DEMO_ALL_UNITS = "demo:all-units"


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
    auth_mode: str = os.getenv("FORTIFY_AUTH_MODE", "demo").strip() or "demo"
    # Object-level scope for the unauthenticated demonstration build. Defaults
    # to the named demo-wide permission so the prototype stays usable; set it to
    # a comma-separated list of real unit ids (e.g. "U-011,U-012") to exercise
    # unit scoping, or to an empty value to see the fail-closed behaviour.
    demo_unit_scope: str = os.getenv("FORTIFY_DEMO_UNIT_SCOPE", DEMO_ALL_UNITS).strip()


settings = Settings()
