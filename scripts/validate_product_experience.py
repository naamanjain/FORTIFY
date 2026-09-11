from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for path in (ROOT, BACKEND):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.api.routes import dashboard as dashboard_route  # noqa: E402

WELFARE = {"X-Fortify-Role": "WELFARE_OFFICER", "X-Fortify-Purpose": "WELFARE_SUPPORT"}
COMMAND = {"X-Fortify-Role": "COMMANDER", "X-Fortify-Purpose": "AGGREGATE_OPERATIONS"}
ADMIN = {"X-Fortify-Role": "SYSTEM_ADMINISTRATOR", "X-Fortify-Purpose": "INFRASTRUCTURE_ADMIN"}


def main() -> int:
    with TemporaryDirectory() as tmp:
        dashboard_route.AUDIT_PATH = Path(tmp) / "audit.jsonl"
        with TestClient(app) as client:
            overview = client.get("/api/dashboard/overview", headers=WELFARE)
            personnel = client.get("/api/dashboard/personnel", headers=WELFARE)
            units = client.get("/api/dashboard/units", headers=COMMAND)
            unit_detail = client.get("/api/dashboard/unit/U-011", headers=COMMAND)
            sources = client.get("/api/dashboard/data-sources", headers=COMMAND)
            health = client.get("/api/dashboard/system-health", headers=ADMIN)
            search_person = client.get("/api/dashboard/search?query=P-0001", headers=WELFARE)
            search_unit = client.get("/api/dashboard/search?query=U-011", headers=COMMAND)

        checks = [
            (overview.status_code == 200 and overview.json()["personnel_count"] == 500, "overview population"),
            (personnel.status_code == 200 and personnel.json()["total_personnel"] == 500, "personnel coverage"),
            (units.status_code == 200 and len(units.json()["units"]) == 18, "unit coverage"),
            (unit_detail.status_code == 200 and unit_detail.json()["personnel"] > 0, "unit detail"),
            (sources.status_code == 200 and len(sources.json()["sources"]) >= 8, "source provenance"),
            (health.status_code == 200 and health.json()["synthetic_demo"] is True, "system health"),
            (search_person.status_code == 200 and any(r["type"] == "PERSONNEL" for r in search_person.json()["results"]), "person search"),
            (search_unit.status_code == 200 and all(r["type"] == "UNIT" for r in search_unit.json()["results"]), "aggregate search"),
            ("perceived_stress" not in sources.text.lower() and "mood_score" not in sources.text.lower(), "privacy"),
        ]
        failed = [name for ok, name in checks if not ok]
        if failed:
            print("VALIDATION FAILED:", ", ".join(failed))
            return 1
        print("PHASE 13 PRODUCT EXPERIENCE VALIDATION PASSED")
        print("Personnel:", personnel.json()["total_personnel"])
        print("Units:", len(units.json()["units"]))
        print("Source surfaces:", len(sources.json()["sources"]))
        print("Privacy schema: PASS")
        print("Role-aware search: PASS")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
