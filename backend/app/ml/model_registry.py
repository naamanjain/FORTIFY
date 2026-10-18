"""Lightweight model registry: explicit, auditable model promotion.

The registry answers one governance question: *which artifact set is current,
and who decided that?* It supports:

* **current** — the artifact set the API/pipeline treat as live.
* **candidate** — a freshly trained set that has NOT been promoted; nothing
  consumes it automatically.
* **retired** — previous currents, kept with rollback metadata (the artifact
  paths they pointed at, and why they were replaced).

Promotion is always an explicit human action (`scripts/promote_model.py`),
requires the candidate to pass the compatibility gate and carry a validation
report, writes an audit event, and never happens automatically — not on a
schedule, not on a metric, not on a deploy.

The registry is a JSON file (artifacts/model_registry.json), version-controlled
in *structure* but produced at runtime. For a departmental deployment this
file belongs under change control alongside the audit log.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .model_compat import verify as verify_compatibility

REGISTRY_VERSION = "model-registry-v1"
STATUSES = ("candidate", "current", "retired")


@dataclass
class RegistryEntry:
    model_id: str
    status: str
    phase4_metadata: str
    phase5_card: str
    validation_report: str | None = None
    registered_at: str = ""
    promoted_at: str | None = None
    promoted_by: str | None = None
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "status": self.status,
            "phase4_metadata": self.phase4_metadata,
            "phase5_card": self.phase5_card,
            "validation_report": self.validation_report,
            "registered_at": self.registered_at,
            "promoted_at": self.promoted_at,
            "promoted_by": self.promoted_by,
            "notes": self.notes,
        }


class ModelRegistry:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"registry_version": REGISTRY_VERSION, "current": None, "entries": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, data: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def register_candidate(
        self,
        model_id: str,
        phase4_metadata: Path,
        phase5_card: Path,
        validation_report: Path | None = None,
        notes: str = "",
    ) -> RegistryEntry:
        """Record a freshly trained artifact set as a candidate.

        Refuses to overwrite an existing model_id with a different status.
        Registers ONLY: no artifact becomes current here, whatever its metrics.
        """
        data = self._load()
        for entry in data["entries"]:
            if entry["model_id"] == model_id and entry["status"] in ("current", "candidate"):
                raise ValueError(
                    f"model_id {model_id!r} is already registered as {entry['status']!r}; "
                    "use a new model_id (e.g. include a version or timestamp)."
                )
        entry = RegistryEntry(
            model_id=model_id,
            status="candidate",
            phase4_metadata=str(phase4_metadata),
            phase5_card=str(phase5_card),
            validation_report=str(validation_report) if validation_report else None,
            registered_at=datetime.now(timezone.utc).isoformat(),
            notes=notes,
        )
        data["entries"].append(entry.as_dict())
        self._save(data)
        return entry

    def promote(
        self,
        model_id: str,
        *,
        promoted_by: str,
        features_csv: Path,
    ) -> RegistryEntry:
        """Promote a candidate to current, after verification.

        The compatibility gate (model <-> feature schema <-> pipeline version)
        and the presence of a validation report are hard requirements. The
        previous current is kept as `retired` with a rollback pointer.
        """
        data = self._load()
        candidates = [e for e in data["entries"] if e["model_id"] == model_id and e["status"] == "candidate"]
        if not candidates:
            raise ValueError(f"No candidate registered under {model_id!r}.")
        # Work on the dict form throughout so saved state and returned state
        # cannot drift apart.
        entry = candidates[-1]

        compat = verify_compatibility(
            features_csv,
            Path(entry["phase4_metadata"]),
            Path(entry["phase5_card"]),
        )
        if not compat.compatible:
            failed = [c["check"] for c in compat.checks if not c["ok"]]
            raise ValueError(f"Promotion blocked: compatibility checks failed: {failed}")

        if not entry.get("validation_report") or not Path(entry["validation_report"]).exists():
            raise ValueError("Promotion blocked: candidate has no validation report.")

        now = datetime.now(timezone.utc).isoformat()
        for other in data["entries"]:
            if other["status"] == "current":
                other["status"] = "retired"
                other["notes"] = (other.get("notes", "") + f" | retired {now} by {promoted_by}").strip(" |")
        entry["status"] = "current"
        entry["promoted_at"] = now
        entry["promoted_by"] = promoted_by
        data["current"] = dict(entry)
        data["promoted_at"] = now
        self._save(data)
        return RegistryEntry(**{k: v for k, v in entry.items() if k in RegistryEntry.__dataclass_fields__})

    def current(self) -> dict[str, Any] | None:
        return self._load().get("current")

    def rollback_target(self) -> dict[str, Any] | None:
        """The most recently retired entry, for a human-driven rollback."""
        retired = [e for e in self._load()["entries"] if e["status"] == "retired"]
        return retired[-1] if retired else None