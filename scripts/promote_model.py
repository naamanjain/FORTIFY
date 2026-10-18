"""Explicit model promotion (never automatic).

Registers the freshly trained artifact set as a candidate, optionally promotes
it to current after the compatibility gate, and records the decision in the
append-only audit log.

Usage:
    python scripts/promote_model.py --register --model-id phase4-<hash> \
        --notes "retrained on 2026-10 data"
    python scripts/promote_model.py --promote --model-id phase4-<hash> --promoted-by analyst.name

Promotion REQUIRES a validation report (default: artifacts/model_validity/
model_validity_report.json) and passes the artifact compatibility gate.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for _p in (ROOT, BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.core.paths import AUDIT_PATH  # noqa: E402
from app.ml.model_registry import ModelRegistry  # noqa: E402
from app.security.audit import AuditEvent, AuditLog  # noqa: E402

DEFAULT_REGISTRY = ROOT / "artifacts" / "model_registry.json"
DEFAULT_VALIDATION = ROOT / "artifacts" / "model_validity" / "model_validity_report.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Register or promote a model artifact set.")
    parser.add_argument("--register", action="store_true", help="Register the current artifacts as a candidate")
    parser.add_argument("--promote", action="store_true", help="Promote a candidate to current (explicit human decision)")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--promoted-by", default="unspecified", help="Who made the promotion decision")
    parser.add_argument("--notes", default="")
    parser.add_argument("--validation-report", type=Path, default=DEFAULT_VALIDATION)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    args = parser.parse_args()

    registry = ModelRegistry(args.registry)
    phase4 = ROOT / "artifacts" / "phase4" / "model_metadata.json"
    phase5 = ROOT / "artifacts" / "phase5" / "model_card.json"
    features = ROOT / "data" / "generated" / "person_day_features_baseline.csv"

    if args.register:
        if not args.validation_report.exists():
            raise SystemExit(
                f"No validation report at {args.validation_report}; run scripts/validate_model_validity.py first."
            )
        entry = registry.register_candidate(args.model_id, phase4, phase5,
                                            validation_report=args.validation_report, notes=args.notes)
        AuditLog(AUDIT_PATH).append(AuditEvent(
            "MODEL_REGISTERED", "SYSTEM_ADMINISTRATOR", "INFRASTRUCTURE_ADMIN", "ALLOWED",
            f"model/{args.model_id}", entry.registered_at,
            {"status": "candidate", "validation_report": str(entry.validation_report)}))
        print(f"Registered candidate: {args.model_id} (nothing consumes it until promoted)")

    if args.promote:
        entry = registry.promote(args.model_id, promoted_by=args.promoted_by, features_csv=features)
        AuditLog(AUDIT_PATH).append(AuditEvent(
            "MODEL_PROMOTED", "SYSTEM_ADMINISTRATOR", "INFRASTRUCTURE_ADMIN", "ALLOWED",
            f"model/{args.model_id}", entry.promoted_at or "",
            {"promoted_by": args.promoted_by, "status": "current"}))
        print(f"Promoted {args.model_id} to current by {args.promoted_by}; audit event written.")

    rollback = registry.rollback_target()
    if rollback:
        print(f"Rollback target: {rollback['model_id']} ({rollback['phase4_metadata']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())