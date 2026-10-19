"""Ingestion API: the only door for external departmental data.

The endpoint is **opt-in** (`FORTIFY_ENABLE_INGEST=1`), infrastructure-gated,
and validation-only: an accepted batch is staged to disk with a quality
report. It never writes to the feature store, the model, or the review queue
- the deterministic pipeline is the only path from raw records to welfare
signals. Invalid batches are rejected in full with a machine-readable report;
partial ingestion of unvalidated welfare data is worse than none.

Every file this module writes lives under the resolved staging root and is
named from a server-generated identifier. The caller-supplied ``dataset`` is
matched against the schema registry before any staging write, and the
caller-supplied ``batch_id`` is validated and kept as metadata only - it never
becomes a path component. Duplicate ``(source_system, batch_id)`` submissions
are refused with 409 so a retried upload cannot stage the same batch twice.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.dependencies import require_infrastructure, require_principal
from app.core.paths import AUDIT_PATH, DATA_DIR, RUNTIME_DIR
from app.ingestion.boundary import DATASET_SCHEMAS, validate_batch
from app.observability import METRICS
from app.security.principal import Principal

# 16 MiB is roughly 100k+ duty-event rows; a larger batch is a bulk export,
# not an incremental feed. The nginx edge limit must stay in step (see
# frontend/nginx.conf and the consistency test).
MAX_BATCH_BYTES = 16 * 1024 * 1024
READ_CHUNK_BYTES = 1024 * 1024

# External identifiers are metadata only: bounded, printable, and free of path
# separators. The server never derives a filename from this value.
BATCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_SOURCE_SYSTEM_CHARS = 128


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


def _staging_root() -> Path:
    return STAGING_DIR.resolve()


def _contained(target: Path) -> Path:
    """Canonicalise ``target`` and prove it sits under the staging root.

    Resolution follows symlinks, so a dataset directory swapped for a link to
    somewhere else fails closed instead of receiving a write.
    """
    resolved = target.resolve()
    try:
        resolved.relative_to(_staging_root())
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Invalid ingestion staging path.") from exc
    return resolved


def _dataset_dir(dataset: str) -> Path:
    """Return the staging directory for an allow-listed dataset.

    The registry check runs before any filesystem operation: an unknown or
    traversal-shaped dataset name is refused and never reaches a path join.
    """
    if dataset not in DATASET_SCHEMAS:
        raise HTTPException(status_code=404, detail="Unknown dataset.")
    candidate = _staging_root() / dataset
    return _contained(candidate)


def _staging_file(dataset_dir: Path, filename: str) -> Path:
    return _contained(dataset_dir / filename)


def _validated_metadata(source_system: str, batch_id: str) -> tuple[str, str]:
    source = source_system.strip()
    if not source or len(source) > MAX_SOURCE_SYSTEM_CHARS or not source.isprintable():
        raise HTTPException(
            status_code=422,
            detail=f"source_system must be 1-{MAX_SOURCE_SYSTEM_CHARS} printable characters.",
        )
    if not BATCH_ID_PATTERN.fullmatch(batch_id):
        raise HTTPException(
            status_code=422,
            detail="batch_id must be 1-128 characters using letters, digits, '.', '_', ':', or '-'.",
        )
    return source, batch_id


async def _read_bounded(file: UploadFile) -> bytes:
    """Read the upload in fixed-size chunks, refusing as soon as the cap is
    crossed. ``Content-Length`` is never trusted; memory is bounded by the cap
    plus one chunk rather than by whatever the caller sends."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_BATCH_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Batch exceeds the {MAX_BATCH_BYTES} byte limit.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _claim_batch(dataset_dir: Path, source_system: str, batch_id: str, ingest_id: str) -> bool:
    """Reserve an external batch id atomically; False means it was already used.

    O_EXCL creation makes duplicate detection work across threads and
    processes. The marker is written before staging, so a retried upload can
    never stage a second copy even when two requests arrive together.
    """
    key = hashlib.sha256(f"{source_system}\x00{batch_id}".encode("utf-8")).hexdigest()[:32]
    claim_path = _staging_file(dataset_dir, f"claim-{key}.json")
    dataset_dir.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(claim_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "source_system": source_system,
            "batch_id": batch_id,
            "ingest_id": ingest_id,
            "claimed_at": datetime.now(timezone.utc).isoformat(),
        }))
    return True


def _write_report(dataset_dir: Path, ingest_id: str, payload: dict[str, Any]) -> Path:
    """Write the per-batch report under a server-generated filename."""
    target = _staging_file(dataset_dir, f"batch-{ingest_id}.json")
    dataset_dir.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    os.replace(temporary, target)
    return target


def _quality_report(dataset: str) -> dict[str, Any]:
    """Aggregate the per-batch reports into an ingestion-quality summary."""
    reports_dir = _dataset_dir(dataset)
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
    principal: Principal = Depends(require_principal),
) -> dict[str, Any]:
    """Receive one batch from an authorised departmental feed.

    Requires the infrastructure-administration principal AND the explicit
    opt-in flag; without either, the endpoint does not exist (404) so the
    surface is invisible in the demo deployment.
    """
    require_infrastructure(principal, f"/api/ingest/{dataset}", AUDIT_PATH)

    dataset_dir = _dataset_dir(dataset)
    source_system, batch_id = _validated_metadata(source_system, batch_id)

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=415, detail="Only CSV batches are accepted.")
    content = await _read_bounded(file)

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

    ingest_id = secrets.token_hex(16)
    result.provenance["ingest_id"] = ingest_id

    if not result.accepted:
        METRICS.increment("ingestion_batches_total", outcome="rejected")
    else:
        if not _claim_batch(dataset_dir, source_system, batch_id, ingest_id):
            METRICS.increment("ingestion_batches_total", outcome="duplicate")
            raise HTTPException(
                status_code=409,
                detail="This batch_id has already been ingested for this source_system.",
            )
        METRICS.increment("ingestion_batches_total", outcome="accepted")
        # Stage the validated data and its report; the pipeline picks staged
        # batches up explicitly. Nothing here touches features or scores.
        staged_path = _staging_file(dataset_dir, f"staged-{ingest_id}.csv")
        dataset_dir.mkdir(parents=True, exist_ok=True)
        frame.to_csv(staged_path, index=False)
        result.provenance["staged_path"] = str(staged_path)

    _write_report(dataset_dir, ingest_id, result.as_dict())

    return {
        "accepted": result.accepted,
        "dataset": dataset,
        "ingest_id": ingest_id,
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
def ingestion_status(principal: Principal = Depends(require_principal)) -> dict[str, Any]:
    """Ingestion-quality report: last successful ingestion, invalid counts,
    per-dataset acceptance state. Infrastructure purpose."""
    require_infrastructure(principal, "/api/ingest/status", AUDIT_PATH)
    datasets = {}
    for dataset in DATASET_SCHEMAS:
        datasets[dataset] = _quality_report(dataset)
    return {"enabled": _ingestion_enabled(), "datasets": datasets,
            "generated_at": datetime.now(timezone.utc).isoformat()}
