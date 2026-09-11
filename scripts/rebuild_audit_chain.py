from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for path in (ROOT, BACKEND):
    if str(path) not in os.sys.path:
        os.sys.path.insert(0, str(path))

from app.security.audit import AuditEvent, AuditLog


def _read_events(path: Path) -> list[AuditEvent]:
    events: list[AuditEvent] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        events.append(
            AuditEvent(
                event_type=str(record["event_type"]),
                actor_role=str(record["actor_role"]),
                purpose=str(record["purpose"]),
                outcome=str(record["outcome"]),
                resource=str(record["resource"]),
                timestamp=str(record["timestamp"]),
                details=dict(record.get("details") or {}),
            )
        )
    if not events:
        raise ValueError(f"Audit log is empty: {path}")
    return events


def rebuild(path: Path) -> int:
    events = _read_events(path)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".jsonl",
        prefix="audit_rebuild_",
        dir=path.parent,
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)

    try:
        rebuilt = AuditLog(temp_path)
        for event in events:
            rebuilt.append(event)
        if not rebuilt.verify_chain():
            raise RuntimeError("Rebuilt audit log failed hash-chain verification")
        os.replace(temp_path, path)
        return len(events)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild a FORTIFY audit log through the AuditLog writer")
    parser.add_argument(
        "--path",
        default=str(ROOT / "artifacts" / "phase8" / "dashboard_audit.jsonl"),
        help="Audit JSONL path to rebuild",
    )
    args = parser.parse_args()
    path = Path(args.path)
    if not path.exists():
        raise SystemExit(f"Audit log not found: {path}")
    count = rebuild(path)
    print(f"AUDIT CHAIN REBUILT: {count} events")
    print(f"AUDIT VALID: {AuditLog(path).verify_chain()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
