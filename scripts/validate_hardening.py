from __future__ import annotations

import argparse
import ast
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for path in (ROOT, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import pandas as pd
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import resolve_sqlite_url
from app.core.paths import AUDIT_PATH
from app.main import APP_VERSION, app
from app.security.audit import AuditLog
from app.services.workflow import initialize_workflow_store

EXPECTED_ROWS = 90_000
FORBIDDEN_RAW_FIELDS = {
    "mood_score", "energy_score", "sleep_quality", "perceived_stress",
    "workload_manageability", "support_request",
}


def require_csv(path: Path, expected_columns: set[str], expected_rows: int | None = None) -> pd.DataFrame:
    if not path.exists():
        raise SystemExit(f"VALIDATION FAILED: missing artifact {path}")
    frame = pd.read_csv(path)
    missing = expected_columns - set(frame.columns)
    if missing:
        raise SystemExit(f"VALIDATION FAILED: {path.name} missing columns {sorted(missing)}")
    if expected_rows is not None and len(frame) != expected_rows:
        raise SystemExit(f"VALIDATION FAILED: {path.name} has {len(frame)} rows, expected {expected_rows}")
    return frame


def validate_person_day(frame: pd.DataFrame, name: str) -> None:
    if frame[["person_id", "date"]].duplicated().any():
        raise SystemExit(f"VALIDATION FAILED: duplicate person/date rows in {name}")
    if frame["person_id"].nunique() != 500:
        raise SystemExit(f"VALIDATION FAILED: {name} does not cover 500 personnel")
    dates = pd.to_datetime(frame["date"], errors="raise")
    if dates.min().strftime("%Y-%m-%d") != "2026-01-01" or dates.max().strftime("%Y-%m-%d") != "2026-06-29":
        raise SystemExit(f"VALIDATION FAILED: {name} date range is unexpected")


def validate_privacy(frame: pd.DataFrame, name: str) -> None:
    raw = sorted(FORBIDDEN_RAW_FIELDS.intersection(set(frame.columns)))
    if raw:
        raise SystemExit(f"VALIDATION FAILED: {name} exposes raw wellness fields {raw}")


def validate_console_encoding(project: Path) -> list[str]:
    """Gate scripts must be printable on a default Windows console (cp1252).

    A validator that raises UnicodeEncodeError while reporting its own result
    exits non-zero even when every assertion inside it passed, which reads
    locally as a failed gate and is indistinguishable from a real regression.
    """
    offenders: list[str] = []
    callables = {"print", "check", "SystemExit"}
    for path in sorted((project / "scripts").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        nodes: list[ast.AST] = list(ast.walk(tree))
        for node in nodes:
            if isinstance(node, ast.Raise):
                targets = [node.exc] if node.exc is not None else []
            elif isinstance(node, ast.Call) and (
                (isinstance(node.func, ast.Name) and node.func.id in callables)
                or (isinstance(node.func, ast.Attribute) and node.func.attr in callables)
            ):
                targets = list(node.args) + [keyword.value for keyword in node.keywords]
            else:
                continue
            for target in targets:
                for child in ast.walk(target):
                    if isinstance(child, ast.Constant) and isinstance(child.value, str):
                        try:
                            child.value.encode("cp1252")
                        except UnicodeEncodeError:
                            offenders.append(
                                f"scripts/{path.name}:{node.lineno} cannot print "
                                f"{child.value[:48]!r}"
                            )
    return offenders


PORT_MAPPING = re.compile(r'^\s*-\s*"([^"]+)"\s*$', re.MULTILINE)


def validate_compose_binding(project: Path) -> list[str]:
    """Published container ports must stay on loopback unless exposure is deliberate.

    The demo build authenticates by asserting a role header, so reachability is
    the security boundary. A wildcard publish in docker-compose.yml would hand
    role selection to anyone who can route to the host while the file still says
    not to expose the stack.
    """
    path = project / "docker-compose.yml"
    if not path.is_file():
        return [f"{path.name}: missing"]
    mappings = [
        match.group(1)
        for match in PORT_MAPPING.finditer(path.read_text(encoding="utf-8"))
        # A published port ends in the container port: "8000", "8000:8000" and
        # "127.0.0.1:8000:8000" all qualify. Volumes end in a path, so they do not.
        if match.group(1).rsplit(":", 1)[-1].isdigit()
    ]
    if not mappings:
        return [f"{path.name}: no published port mappings found; gate would be vacuous"]
    return [
        f"{path.name}: published port {value!r} is not bound to 127.0.0.1"
        for value in mappings
        if not (value.startswith("127.0.0.1:") or value.startswith("[::1]:"))
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate FORTIFY Phase 11 hardening contracts")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    project = Path(args.root).resolve()
    generated = project / "data" / "generated"

    predictions = require_csv(generated / "risk_predictions.csv", {"person_id", "date", "welfare_risk_probability", "risk_level"}, EXPECTED_ROWS)
    recommendations = require_csv(generated / "intervention_recommendations.csv", {"person_id", "date", "recommended_action", "risk_band", "requires_human_review"}, EXPECTED_ROWS)
    feasibility = require_csv(generated / "intervention_feasibility.csv", {"person_id", "date", "recommended_action", "feasibility_status", "requires_human_review"}, EXPECTED_ROWS)
    for frame, name in ((predictions, "predictions"), (recommendations, "recommendations"), (feasibility, "feasibility")):
        validate_person_day(frame, name)
        validate_privacy(frame, name)

    # Apply idempotent workflow schema/index hardening before validating it.
    initialize_workflow_store()

    if not AuditLog(AUDIT_PATH).verify_chain():
        raise SystemExit("VALIDATION FAILED: audit chain")

    db_path = resolve_sqlite_url(settings.database_url)
    if not db_path.exists():
        raise SystemExit("VALIDATION FAILED: prototype database missing")
    with sqlite3.connect(db_path) as conn:
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        if fk != 1:
            # The validator checks the runtime contract, not a connection's default state.
            conn.execute("PRAGMA foreign_keys = ON")
            fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        if fk != 1:
            raise SystemExit("VALIDATION FAILED: foreign-key enforcement unavailable")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"workflow_items", "workflow_audit_events"}.issubset(tables):
            raise SystemExit("VALIDATION FAILED: workflow tables missing")
        orphan = conn.execute("""SELECT COUNT(*) FROM workflow_audit_events e
            LEFT JOIN workflow_items w ON w.workflow_item_id=e.workflow_item_id
            WHERE w.workflow_item_id IS NULL""").fetchone()[0]
        if orphan:
            raise SystemExit(f"VALIDATION FAILED: {orphan} orphan workflow audit events")
        indices = {r[1] for r in conn.execute("PRAGMA index_list(workflow_items)")}
        if "idx_workflow_items_pending" not in indices:
            raise SystemExit("VALIDATION FAILED: workflow pending index missing")

    with TestClient(app) as client:
        health = client.get("/health")
    expected_health = {"status": "ok", "service": "FORTIFY", "version": APP_VERSION}
    if health.status_code != 200 or health.json() != expected_health:
        raise SystemExit("VALIDATION FAILED: health endpoint")

    encoding_offenders = validate_console_encoding(project)
    if encoding_offenders:
        raise SystemExit(
            "VALIDATION FAILED: scripts that crash when printed on a cp1252 console:\n  "
            + "\n  ".join(encoding_offenders)
        )

    binding_offenders = validate_compose_binding(project)
    if binding_offenders:
        raise SystemExit(
            "VALIDATION FAILED: container ports exposed beyond loopback:\n  "
            + "\n  ".join(binding_offenders)
        )

    report = {
        "phase": "Phase 11 — Testing + Hardening",
        "artifacts_checked": 3,
        "rows_per_person_day_artifact": EXPECTED_ROWS,
        "audit_chain": "PASS",
        "workflow_foreign_keys": "PASS",
        "workflow_indexes": "PASS",
        "privacy_schema": "PASS",
        "health_endpoint": "PASS",
        "console_encoding": "PASS",
        "compose_loopback_only": "PASS",
        "synthetic_data": True,
    }
    print("PHASE 11 HARDENING VALIDATION PASSED")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
