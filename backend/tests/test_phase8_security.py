from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.security import (
    AccessPurpose,
    AuditEvent,
    AuditLog,
    FieldEncryptor,
    IdentityTokenizer,
    SecurityRole,
    authorize,
    trusted_computation_boundary,
)


SECRET = "phase8-test-token-secret-0123456789"


def test_deterministic_tokenization_and_identity_separation() -> None:
    tokenizer = IdentityTokenizer(SECRET)
    token = tokenizer.tokenize("P-0001")
    assert token.startswith("ptok_")
    assert token == tokenizer.tokenize("P-0001")
    assert tokenizer.verify("P-0001", token)
    assert token != "P-0001"


def test_encryption_roundtrip_and_tamper_rejection() -> None:
    encryptor = FieldEncryptor(FieldEncryptor.generate_key())
    blob = encryptor.encrypt("protected identity mapping")
    assert encryptor.decrypt(blob) == b"protected identity mapping"
    tampered = blob.ciphertext[:-1] + bytes([blob.ciphertext[-1] ^ 1])
    with pytest.raises(ValueError):
        encryptor.decrypt(tampered)


def test_rbac_is_purpose_bound() -> None:
    assert authorize(SecurityRole.WELFARE_OFFICER, AccessPurpose.WELFARE_SUPPORT).allowed
    assert authorize(SecurityRole.COMMANDER, AccessPurpose.WELFARE_SUPPORT).allowed is False
    assert authorize(SecurityRole.AUDITOR, AccessPurpose.AUDIT).allowed
    assert authorize(SecurityRole.SYSTEM_ADMINISTRATOR, AccessPurpose.WELFARE_SUPPORT).allowed is False


def test_audit_hash_chain(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append(AuditEvent("ACCESS", "WELFARE_OFFICER", "WELFARE_SUPPORT", "ALLOWED", "risk_signal", "2026-01-01T00:00:00Z", {}))
    log.append(AuditEvent("ACCESS", "AUDITOR", "AUDIT", "ALLOWED", "audit_log", "2026-01-01T00:01:00Z", {}))
    assert log.verify_chain()
    lines = log.path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["resource"] = "tampered"
    log.path.write_text(json.dumps(record) + "\n" + lines[1] + "\n", encoding="utf-8")
    assert not log.verify_chain()


def test_trusted_boundary_rejects_unprotected_input() -> None:
    with pytest.raises(ValueError):
        with trusted_computation_boundary(protected_input=False):
            pass


def test_trusted_boundary_explicitly_is_not_hardware_tee() -> None:
    with trusted_computation_boundary(protected_input=True) as boundary:
        assert boundary.hardware_tee is False
        assert boundary.protected_input_required is True


def test_sequential_audit_writes_continue_hash_chain(tmp_path: Path) -> None:
    log_path = tmp_path / "sequential.jsonl"
    hashes = []
    for sequence in (1, 2, 3):
        hashes.append(
            AuditLog(log_path).append(
                AuditEvent(
                    "ACCESS",
                    "WELFARE_OFFICER",
                    "WELFARE_SUPPORT",
                    "ALLOWED",
                    "risk_signal",
                    f"2026-01-01T00:0{sequence}:00Z",
                    {"sequence": sequence},
                )
            )
        )

    lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 3
    assert lines[0]["previous_hash"] == "GENESIS"
    assert lines[0]["event_hash"] == hashes[0]
    assert lines[1]["previous_hash"] == lines[0]["event_hash"]
    assert lines[2]["previous_hash"] == lines[1]["event_hash"]
    assert AuditLog(log_path).verify_chain()
