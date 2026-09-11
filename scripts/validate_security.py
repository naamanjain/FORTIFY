from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate FORTIFY Phase 8 security controls.")
    parser.add_argument("--feasibility", default="data/generated/intervention_feasibility.csv")
    parser.add_argument("--predictions", default="data/generated/risk_predictions.csv")
    parser.add_argument("--recommendations", default="data/generated/intervention_recommendations.csv")
    parser.add_argument("--report", default="artifacts/phase8/security_control_report.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    feasibility = pd.read_csv(ROOT / args.feasibility)
    predictions = pd.read_csv(ROOT / args.predictions)
    recommendations = pd.read_csv(ROOT / args.recommendations)

    assert len(feasibility) > 0, "Feasibility artifact is empty"
    assert len(predictions) > 0, "Phase 4/5 prediction artifact is empty"
    assert len(recommendations) > 0, "Phase 6 recommendation artifact is empty"
    assert "person_id" in feasibility.columns
    assert not any("wellness" in col.lower() or "stress" in col.lower() for col in feasibility.columns)
    assert not any("wellness" in col.lower() or "stress" in col.lower() for col in recommendations.columns)

    tokenizer = IdentityTokenizer("phase8-validation-token-secret-0123456789")
    sample_people = feasibility["person_id"].drop_duplicates().head(25).tolist()
    tokens = [tokenizer.tokenize(pid) for pid in sample_people]
    assert len(tokens) == len(set(tokens))
    assert all(token != pid for token, pid in zip(tokens, sample_people))
    assert tokens == [tokenizer.tokenize(pid) for pid in sample_people]

    key = FieldEncryptor.generate_key()
    encryptor = FieldEncryptor(key)
    secret_value = json.dumps({"person_id": "P-0001"}).encode()
    ciphertext = encryptor.encrypt(secret_value)
    assert encryptor.decrypt(ciphertext.ciphertext) == secret_value

    assert authorize(SecurityRole.WELFARE_OFFICER, AccessPurpose.WELFARE_SUPPORT).allowed
    assert not authorize(SecurityRole.COMMANDER, AccessPurpose.WELFARE_SUPPORT).allowed
    assert authorize(SecurityRole.AUDITOR, AccessPurpose.AUDIT).allowed

    audit_path = ROOT / "artifacts/phase8/security_validation_audit.jsonl"
    audit = AuditLog(audit_path)
    audit.append(AuditEvent("VALIDATION", "SYSTEM_ADMINISTRATOR", "INFRASTRUCTURE_ADMIN", "ALLOWED", "security_validation", "2026-01-01T00:00:00Z", {"hash": hashlib.sha256(secret_value).hexdigest()}))
    assert audit.verify_chain()

    with trusted_computation_boundary(protected_input=True) as boundary:
        assert boundary.hardware_tee is False

    report = {
        "phase": 8,
        "status": "validation_passed",
        "input_rows": {"feasibility": len(feasibility), "predictions": len(predictions), "recommendations": len(recommendations)},
        "controls": {
            "tokenization": True,
            "encryption_roundtrip": True,
            "purpose_bound_rbac": True,
            "audit_hash_chain": True,
            "trusted_boundary": True,
            "hardware_tee_claim": False,
            "raw_wellness_in_operational_outputs": False,
        },
        "prototype_boundary": "Application-process trust boundary; hardware-backed TEE is a production architecture item and is not claimed here.",
    }
    report_path = ROOT / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("PHASE 8 SECURITY VALIDATION PASSED")
    print(f"Feasibility rows: {len(feasibility):,}")
    print(f"Predictions rows: {len(predictions):,}")
    print(f"Recommendations rows: {len(recommendations):,}")
    print(f"Report: {report_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
