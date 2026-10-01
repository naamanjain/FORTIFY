from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

# The audit log is tamper-*evident* only in so far as the signing key is held
# outside the log. In this prototype the key comes from
# FORTIFY_AUDIT_HMAC_KEY when supplied, otherwise it is generated once and
# stored beside the log with owner-only permissions. That is enough to detect
# accidental truncation and casual edits, but anyone who can write both the log
# and the sibling key file can still rewrite history. A production deployment
# must inject the key from a secret manager or HSM; see SECURITY_MODEL.md.

_ENV_KEY = "FORTIFY_AUDIT_HMAC_KEY"
_GENESIS = "GENESIS"


@dataclass(frozen=True)
class AuditEvent:
    event_type: str
    actor_role: str
    purpose: str
    outcome: str
    resource: str
    timestamp: str
    details: dict[str, Any]


@dataclass(frozen=True)
class ChainVerification:
    """Outcome of an audit-chain check.

    ``valid`` is fail-closed: an unanchored or truncated log is *not* valid, so
    a caller cannot mistake a missing anchor for an intact log.
    """

    valid: bool
    reason: str
    records: int
    anchored: bool
    head_hash: str


@contextmanager
def _append_lock(lock_path: Path) -> Iterator[None]:
    """Serialize audit append operations across threads and processes.

    The lock is acquired by atomic O_EXCL creation, which works across
    Windows and POSIX processes without third-party dependencies.
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
    """Append-only JSONL audit log with a SHA-256 hash chain and an anchored head.

    Three properties are enforced, and each covers an attack the bare hash chain
    did not:

    * **Integrity** - every record commits to its predecessor, so an edit in the
      middle breaks every later link.
    * **Truncation** - the record count and head hash are mirrored to a separate
      anchor file. Rolling the log back to any prefix no longer verifies,
      because the anchor still describes the longer chain.
    * **Forgery** - the anchor is signed with HMAC-SHA256 under a key kept
      outside the log, so recomputing the chain after rewriting history is not
      enough; the attacker also needs the key.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.path.with_name(f"{self.path.name}.lock")
        self._anchor_path = self.path.with_name(f"{self.path.name}.anchor")
        self._key_path = self.path.with_name(f"{self.path.name}.key")

    # ---- key management -------------------------------------------------

    def _key(self) -> bytes:
        """Resolve the signing key, creating a persistent one on first use."""
        from_env = os.getenv(_ENV_KEY)
        if from_env:
            if len(from_env.encode("utf-8")) < 32:
                raise ValueError(
                    f"{_ENV_KEY} must be at least 32 bytes to sign the audit anchor"
                )
            return from_env.encode("utf-8")
        if self._key_path.exists():
            stored = self._key_path.read_bytes().strip()
            if stored:
                return stored
        key = os.urandom(32)
        self._key_path.write_bytes(key)
        try:
            os.chmod(self._key_path, 0o600)
        except OSError:
            # Best effort: some filesystems (and Windows) do not honour this.
            pass
        return key

    # ---- anchor ---------------------------------------------------------

    def _anchor_payload(self, head_hash: str, count: int) -> dict[str, Any]:
        payload = {"head_hash": head_hash, "records": count}
        signature = hmac.new(
            self._key(),
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {**payload, "signature": signature}

    def _write_anchor(self, head_hash: str, count: int) -> None:
        self._anchor_path.write_text(
            json.dumps(self._anchor_payload(head_hash, count), sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    def _read_anchor(self) -> dict[str, Any] | None:
        if not self._anchor_path.exists():
            return None
        try:
            anchor = json.loads(self._anchor_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return anchor if isinstance(anchor, dict) else None

    # ---- chain ----------------------------------------------------------

    def _recompute_chain(self) -> tuple[str, int, bool]:
        """Return (head_hash, record_count, internal_chain_valid).

        A line that is not parseable JSON marks the chain invalid rather than
        raising: a truncated final record is evidence of a problem to report,
        not a reason to fail the audit check itself with an exception.
        """
        if not self.path.exists():
            return _GENESIS, 0, True
        previous_hash = _GENESIS
        count = 0
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return _GENESIS, 0, False
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                return previous_hash, count, False
            if not isinstance(record, dict):
                return previous_hash, count, False
            record_hash = record.pop("event_hash", None)
            if record.get("previous_hash") != previous_hash:
                return previous_hash, count, False
            canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
            expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if expected != record_hash:
                return previous_hash, count, False
            previous_hash = record_hash
            count += 1
        return previous_hash, count, True

    # ---- public API -----------------------------------------------------

    def append(self, event: AuditEvent) -> str:
        """Append one event, extending the chain and re-anchoring it atomically."""
        with _append_lock(self._lock_path):
            previous_hash = _GENESIS
            count = 0
            if self.path.exists():
                lines = [
                    line
                    for line in self.path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
                if lines:
                    try:
                        previous_hash = json.loads(lines[-1])["event_hash"]
                    except (json.JSONDecodeError, KeyError, TypeError):
                        # A corrupt tail must not be silently overwritten. Refuse
                        # the append so evidence is preserved for an auditor.
                        raise ValueError(
                            "Audit log tail is unreadable; refusing to append. "
                            "Inspect and repair the log before continuing."
                        ) from None
                    count = len(lines)

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
                handle.flush()
                os.fsync(handle.fileno())
            # Anchor after the record is durable: a crash between the two leaves
            # an unanchored log, which verify() reports rather than silently
            # accepting.
            self._write_anchor(event_hash, count + 1)
            return event_hash

    def verify(self) -> ChainVerification:
        """Full verification, including truncation and forgery checks."""
        head_hash, count, internally_valid = self._recompute_chain()
        if not internally_valid:
            return ChainVerification(False, "Hash chain is broken: a record was altered or reordered.", count, True, head_hash)

        anchor = self._read_anchor()
        if anchor is None:
            if count == 0:
                return ChainVerification(True, "Audit log is empty.", 0, True, _GENESIS)
            # Fail closed: records exist but there is nothing to hold the chain
            # to its full length, so the log cannot be shown to be complete.
            return ChainVerification(
                False,
                "Audit anchor is missing; the log cannot be shown to be complete.",
                count,
                False,
                head_hash,
            )

        expected_signature = hmac.new(
            self._key(),
            json.dumps(
                {"head_hash": anchor.get("head_hash"), "records": anchor.get("records")},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_signature, str(anchor.get("signature", ""))):
            return ChainVerification(
                False, "Audit anchor signature is invalid; the anchor was altered.", count, True, head_hash
            )

        if anchor.get("records") != count or anchor.get("head_hash") != head_hash:
            return ChainVerification(
                False,
                "Audit log length or head hash does not match the anchor; records were truncated or removed.",
                count,
                True,
                head_hash,
            )

        return ChainVerification(True, "Audit chain is intact.", count, True, head_hash)

    def verify_chain(self) -> bool:
        """Backwards-compatible boolean form of :meth:`verify`."""
        return self.verify().valid

    def anchor_audit_log(self) -> None:
        """(Re)create the anchor for a pre-existing log written before anchoring.

        This is a one-time bootstrap for logs produced by earlier versions. It
        blesses the current contents, so it should be run deliberately on a log
        already known to be intact - never automatically on a suspect one.
        """
        head_hash, count, valid = self._recompute_chain()
        if not valid:
            raise ValueError("Refusing to anchor an audit log with a broken hash chain")
        self._write_anchor(head_hash, count)