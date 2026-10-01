"""Central repository path resolution.

Every runtime location the API touches is derived from the repository root or
from an environment override, so the application never depends on the working
directory or on machine-specific paths.
"""
from __future__ import annotations

import os
from pathlib import Path

# backend/app/core/paths.py -> backend/app/core -> backend/app -> backend -> repository root
ROOT = Path(__file__).resolve().parents[3]

DATA_DIR = Path(os.getenv("FORTIFY_DATA_DIR", ROOT / "data" / "generated"))
RUNTIME_DIR = Path(os.getenv("FORTIFY_RUNTIME_DIR", ROOT / "data" / "runtime"))
AUDIT_PATH = Path(os.getenv("FORTIFY_AUDIT_LOG", RUNTIME_DIR / "audit.jsonl"))

ARTIFACTS_DIR = ROOT / "artifacts"
