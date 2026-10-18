"""Model artifact compatibility verification.

A deployment must not serve scores from artifacts that disagree with each
other or with the feature schema the pipeline produces. This module states the
compatibility contract explicitly and verifies it:

* model (Phase 4) ↔ its own recorded feature schema hash
* model ↔ Phase 5 probability layer (pipeline version alignment)
* feature schema ↔ the actual person-day feature table on disk

A mismatch is a hard failure in the pipeline (build stops) and a *readiness*
failure at runtime (`/ready` reports model readiness = false). No automatic
retraining, no silent regeneration: an incompatible artifact set is a human
problem to fix.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

# Pipeline versions that may consume each other's artifacts. Bump MINOR when
# artifacts gain fields (backwards compatible), MAJOR when they change meaning.
COMPATIBLE_PIPELINES = {"pipeline-v2-latent-aware"}


@dataclass
class CompatibilityReport:
    compatible: bool
    checks: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"compatible": self.compatible, "checks": self.checks}

    def _check(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append({"check": name, "ok": ok, "detail": detail})
        if not ok:
            self.compatible = False


def feature_schema_hash(features_csv: Path) -> str:
    """A stable hash of the feature table's column names and order.

    Column order matters: the model's feature list is positional, so a
    re-ordered table is a different schema even with identical columns.
    """
    header = pd.read_csv(features_csv, nrows=0)
    digest = hashlib.sha256("|".join(header.columns).encode("utf-8")).hexdigest()
    return f"sha256:{digest[:16]}"


def verify(
    features_csv: Path,
    phase4_metadata_path: Path,
    phase5_card_path: Path | None = None,
) -> CompatibilityReport:
    """Verify the artifact set is mutually compatible. Never raises."""
    report = CompatibilityReport(compatible=True)

    if not features_csv.exists():
        report._check("features_present", False, f"{features_csv} not found")
        return report
    if not phase4_metadata_path.exists():
        report._check("model_metadata_present", False, f"{phase4_metadata_path} not found")
        return report

    actual_schema = feature_schema_hash(features_csv)
    metadata = json.loads(phase4_metadata_path.read_text(encoding="utf-8"))
    recorded_schema = metadata.get("feature_schema_version")
    if recorded_schema:
        report._check(
            "feature_schema_matches_model",
            recorded_schema == actual_schema,
            f"model recorded {recorded_schema}, feature table is {actual_schema}",
        )
    else:
        report._check("feature_schema_matches_model", False,
                      "model metadata does not record a feature schema version")

    columns = metadata.get("feature_columns", [])
    header = list(pd.read_csv(features_csv, nrows=0).columns)
    missing = [c for c in columns if c not in header]
    report._check("model_columns_present", not missing,
                  "all model feature columns exist in the table" if not missing
                  else f"missing columns: {missing[:5]}")

    model_pipeline = metadata.get("pipeline_version")
    if model_pipeline:
        report._check(
            "pipeline_version_supported",
            model_pipeline in COMPATIBLE_PIPELINES,
            f"model trained under {model_pipeline!r}; supported: {sorted(COMPATIBLE_PIPELINES)}",
        )
    else:
        report._check("pipeline_version_supported", False,
                      "model metadata does not record a pipeline version")

    if phase5_card_path is not None and Path(phase5_card_path).exists():
        card = json.loads(Path(phase5_card_path).read_text(encoding="utf-8"))
        card_pipeline = card.get("pipeline", {}).get("pipeline_version")
        report._check(
            "phase5_alignment",
            card_pipeline == model_pipeline,
            f"phase4={model_pipeline!r} phase5={card_pipeline!r}",
        )
        card_model_version = card.get("model_identity", {}).get("phase5_model_version")
        report._check("phase5_version_recorded", bool(card_model_version),
                      f"phase5 model version: {card_model_version}")

    return report


def stamp_metadata(metadata: dict[str, Any], features_csv: Path, pipeline_version: str,
                   training_data_signature: str | None = None) -> dict[str, Any]:
    """Add the compatibility fields to Phase 4 metadata before it is saved."""
    metadata["feature_schema_version"] = feature_schema_hash(features_csv)
    metadata["pipeline_version"] = pipeline_version
    metadata["model_id"] = metadata.get("model_id") or "fortify-phase4-logreg"
    metadata["model_version"] = f"phase4-{metadata['feature_schema_version'][-8:]}"
    metadata["trained_at"] = datetime.now(timezone.utc).isoformat()
    metadata["training_data_version"] = training_data_signature or "seed-42-default-world"
    return metadata