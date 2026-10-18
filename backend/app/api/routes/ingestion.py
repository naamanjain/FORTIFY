"""Ingestion API: the only door for external departmental data.

The endpoint is **opt-in** (`FORTIFY_ENABLE_INGEST=1`), infrastructure-gated,
and validation-only: an accepted batch is staged to disk with a quality
report. It never writes to the feature store, the model, or the review queue
- the deterministic pipeline is the only path from raw records to welfare
signals. Invalid batches are rejected in full with a machine-readable report;
partial ingestion of unvalidated welfare data is worse than none.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, Depends as FastAPIDepends, HTTPException, UploadFile, File, Form
import os

from app.api.dependencies import require_infrastructure, require_principal
from app.core.paths import AUDIT_PATH, DATA_DIR, RUNTIME_DIR
from app.ingestion.boundary import validate_batch
from app.observability import METRICS
from app.security.principal import Principal

def _require_ingest_enabled() -> None:
    """Opt-in gate as a router dependency so it runs BEFORE body validation:
    a disabled deployment answers 404 (surface invisible), not 422."""
    if not _ingestion_enabled():
        raise HTTPException(status_code=404, detail="Ingestion is not enabled on this deployment.")


router = APIRouter(prefix="/api/ingest", tags=["ingestion"],
                   dependencies=[Depends(_require_ingest_enabled)])

STAGING_DIR = RUNTIME_DIR / "ingestion-staging"


def _ingestion_enabled() -> bool:
    return os.getenv("FORTIFY_ENABLE_INGEST", "").strip() == "1"


def _known_latest_date() -> Any | None:
    """Latest event date already known, for staleness comparison."""
    duty = DATA_DIR / "duty_events.csv"
    if not duty.exists():
        return None
    dates = pd.read_csv(duty, usecols=["date"])["date"]
    parsed = pd.to_datetime(dates, errors="coerce").dropna()
    return parsed.max().date() if not parsed.empty else None


def _quality_report(dataset: str) -> dict[str, Any]:
    """Aggregate the per-batch reports into an ingestion-quality summary."""
    reports_dir = STAGING_DIR / dataset
    if not reports_dir.exists():
        return {"batches": 0, "accepted": 0, "rejected": 0, "last_ingestion": None,
                "invalid_record_count": 0}
    batches = sorted(reports_dir.glob("batch-*.json"))
    accepted = rejected = invalid = 0
    last = None
    for path in batches:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["accepted"]:
            accepted += 1
        else:
            rejected += 1
        invalid += sum(r["count"] for r in record["rejections"])
        last = record["provenance"]["received_at"]
    return {"batches": len(batches), "accepted": accepted, "rejected": rejected,
            "last_ingestion": last, "invalid_record_count": invalid}


@router.post("/{dataset}")
async def ingest(
    dataset: str,
    file: UploadFile = File(...),
    source_system: str = Form(...),
    batch_id: str = Form(...),
    schema_version: int = Form(default=1),
    principal: Principal = FastAPIDepends(require_principal),
) -> dict[str, Any]:
    """Receive one batch from an authorised departmental feed.

    Requires the infrastructure-administration principal AND the explicit
    opt-in flag; without either, the endpoint does not exist (404) so the
    surface is invisible in the demo deployment.
    """
    require_infrastructure(principal, f"/api/ingest/{dataset}", AUDIT_PATH)

    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=415, detail="Only CSV batches are accepted.")
    content = await file.read()
    if len(content) > 64 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Batch exceeds the 64 MiB limit.")

    import io
    try:
        frame = pd.read_csv(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001 - parser errors are client faults
        raise HTTPException(status_code=422, detail="Batch is not parseable CSV.") from exc

    result = validate_batch(
        dataset, frame,
        source_system=source_system,
        batch_id=batch_id,
        schema_version=schema_version,
        known_latest_date=_known_latest_date(),
    )
    if not result.accepted:
        METRICS.increment("ingestion_batches_total", outcome="rejected")
    else:
        METRICS.increment("ingestion_batches_total", outcome="accepted")
        # Stage the validated data and its report; the pipeline picks staged
        # batches up explicitly. Nothing here touches features or scores.
        dataset_dir = STAGING_DIR / dataset
        dataset_dir.mkdir(parents=True, exist_ok=True)
        safe_batch = "".join(c for c in batch_id if c.isalnum() or c in "-_")[:64] or "batch"
        staged_path = dataset_dir / f"staged-{safe_batch}.csv"
        frame.to_csv(staged_path, index=False)
        result.provenance["staged_path"] = str(staged_path)

    (STAGING_DIR / dataset / f"batch-{result.provenance['batch_id'][:64]}.json").parent.mkdir(
        parents=True, exist_ok=True)
    (STAGING_DIR / dataset / f"batch-{result.provenance['batch_id'][:64]}.json").write_text(
        json.dumps(result.as_dict(), indent=2, default=str), encoding="utf-8")

    return {
        "accepted": result.accepted,
        "dataset": dataset,
        "rows": result.rows,
        "rejections": [r.as_dict() for r in result.rejections],
        "provenance": result.provenance,
        "note": (
            "Accepted batches are staged for the deterministic pipeline; they do "
            "not become features, scores, or review-queue entries until the "
            "pipeline ingests them."
        ) if result.accepted else "Batch rejected in full; nothing was staged.",
    }


@router.get("/status")
def ingestion_status(principal: Principal = FastAPIDepends(require_principal)) -> dict[str, Any]:
    """Ingestion-quality report: last successful ingestion, invalid counts,
    per-dataset acceptance state. Infrastructure purpose."""
    require_infrastructure(principal, "/api/ingest/status", AUDIT_PATH)
    datasets = {}
    for dataset in ("duty_events", "recovery_events", "incident_events",
                    "training_events", "wellness_events", "leave_events", "deployment_events"):
        datasets[dataset] = _quality_report(dataset)
    return {"enabled": _ingestion_enabled(), "datasets": datasets,
            "generated_at": datetime.now(timezone.utc).isoformat()}