from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


@dataclass(frozen=True)
class AuditEvent:
    event_type: str
    actor_role: str
    purpose: str
    outcome: str
    resource: str
    timestamp: str
    details: dict[str, Any]


@contextmanager
def _append_lock(lock_path: Path) -> Iterator[None]:
    """Serialize audit append operations across threads and processes.

    The lock is acquired by atomic O_EXCL creation, which works across
    Windows and POSIX processes without third-party dependencies. The
    previous implementation relied on a byte-range lock whose behavior was
    not reliable enough for the dashboard's concurrent writers.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    acquired = False
    lock_fd: int | None = None
    stale_after = 300.0

    try:
        while not acquired:
            try:
                lock_fd = os.open(
                    lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                os.write(lock_fd, str(os.getpid()).encode("ascii"))
                os.close(lock_fd)
                lock_fd = None
                acquired = True
            except FileExistsError:
                try:
                    age = time.time() - lock_path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age > stale_after:
                    try:
                        lock_path.unlink()
                    except FileNotFoundError:
                        continue
                    continue
                time.sleep(0.01)

        yield
    finally:
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except OSError:
                pass
        if acquired:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


class AuditLog:
    """Append-only JSONL audit log with a SHA-256 hash chain."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.path.with_name(f"{self.path.name}.lock")

    def append(self, event: AuditEvent) -> str:
        # Reading the current tail hash and appending the new event are one
        # serialized operation. GENESIS is used only for a genuinely empty log.
        with _append_lock(self._lock_path):
            previous_hash = "GENESIS"
            if self.path.exists():
                lines = [
                    line
                    for line in self.path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                if lines:
                    previous_hash = json.loads(lines[-1])["event_hash"]

            payload = {
                "event_type": event.event_type,
                "actor_role": event.actor_role,
                "purpose": event.purpose,
                "outcome": event.outcome,
                "resource": event.resource,
                "timestamp": event.timestamp,
                "details": event.details,
                "previous_hash": previous_hash,
            }
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            event_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            payload["event_hash"] = event_hash
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
            return event_hash

    def verify_chain(self) -> bool:
        if not self.path.exists():
            return True
        previous_hash = "GENESIS"
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            actual = record.pop("event_hash")
            if record.get("previous_hash") != previous_hash:
                return False
            canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
            expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if expected != actual:
                return False
            previous_hash = actual
        return True
