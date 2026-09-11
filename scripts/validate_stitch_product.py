from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient
from app.main import app

WELFARE = {"X-Fortify-Role": "WELFARE_OFFICER", "X-Fortify-Purpose": "WELFARE_SUPPORT"}
COMMAND = {"X-Fortify-Role": "COMMANDER", "X-Fortify-Purpose": "AGGREGATE_OPERATIONS"}
AUDITOR = {"X-Fortify-Role": "AUDITOR", "X-Fortify-Purpose": "AUDIT"}


def main() -> int:
    required = [
        ROOT / "frontend/src/App.tsx",
        ROOT / "frontend/src/pages/Attention.tsx",
        ROOT / "frontend/src/pages/PersonProfile.tsx",
        ROOT / "frontend/src/pages/UnitCommand.tsx",
        ROOT / "frontend/src/pages/DataSignals.tsx",
        ROOT / "frontend/src/pages/DataCollection.tsx",
        ROOT / "frontend/src/pages/Governance.tsx",
    ]
    if not all(p.exists() for p in required):
        print("PHASE 13.2 VALIDATION FAILED: required frontend files missing")
        return 1
    source_text = "\n".join(p.read_text(encoding="utf-8") for p in required)
    for forbidden in ("P-0144", "U-031", "perceived_stress", "mood_score", "calibrated_probability"):
        if forbidden in source_text:
            print(f"PHASE 13.2 VALIDATION FAILED: hard-coded/raw field {forbidden}")
            return 1

    with TestClient(app) as client:
        attention = client.get("/api/dashboard/overview", headers=WELFARE)
        person_a = client.get("/api/dashboard/person/P-0144", headers=WELFARE)
        person_b = client.get("/api/dashboard/person/P-0209", headers=WELFARE)
        unit = client.get("/api/dashboard/unit/U-031", headers=COMMAND)
        sources = client.get("/api/dashboard/data-sources", headers=COMMAND)
        audit = client.get("/api/dashboard/audit", headers=AUDITOR)
    responses = [attention, person_a, person_b, unit, sources, audit]
    if any(r.status_code != 200 for r in responses):
        print("PHASE 13.2 VALIDATION FAILED: protected API surface returned non-200")
        print(json.dumps({"statuses": [r.status_code for r in responses]}))
        return 1
    a, b = person_a.json(), person_b.json()
    if a["person_id"] == b["person_id"] or a.get("unit_id") == b.get("unit_id") and a.get("role") == b.get("role"):
        print("PHASE 13.2 VALIDATION FAILED: person profile is not dynamic")
        return 1
    if "P-" in unit.text:
        print("PHASE 13.2 VALIDATION FAILED: unit detail exposed individual identifiers")
        return 1
    if not audit.json().get("chain_valid"):
        print("PHASE 13.2 VALIDATION FAILED: audit chain")
        return 1
    summary = attention.json()
    print("PHASE 13.2 PRODUCT VALIDATION PASSED")
    print(f"Personnel: {summary['personnel_count']}")
    print(f"Attention source date: {summary['as_of_date']}")
    print(f"Person dynamic check: {a['person_id']} ({a.get('unit_id')}) vs {b['person_id']} ({b.get('unit_id')})")
    print(f"Unit aggregate check: {unit.json()['unit_id']} ({unit.json()['personnel']} personnel)")
    print(f"Data source metadata count: {len(sources.json()['sources'])}")
    print(f"Audit chain: {audit.json()['chain_valid']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
