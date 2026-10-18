from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.ingestion import router as ingestion_router
from app.api.routes.workflow import router as workflow_router
from app.core.config import settings
from app.core.database import check_database, initialize_database
from app.core.paths import ARTIFACTS_DIR as ROOT_ARTIFACTS
from app.core.paths import DATA_DIR
from app.ml.data_quality import audit as audit_data_quality
from app.ml.data_quality import summarize
from app.observability import METRICS, build_rate_limiter, configure_logging
from app.services.workflow import ensure_workflow_items, initialize_workflow_store

# Single source of truth for the application version, surfaced by /health and
# /version so a deployment can be identified from outside.
APP_VERSION = os.getenv("FORTIFY_APP_VERSION", "0.2.0")

configure_logging()
logger = logging.getLogger("fortify")

# Artifacts the API genuinely needs to serve any data request.
REQUIRED_ARTIFACTS = (
    "intervention_recommendations.csv",
    "intervention_feasibility.csv",
    "personnel.csv",
)


@asynccontextmanager
async def lifespan(application: FastAPI):
    # Startup is deliberately tolerant of broken dependencies: a deployment
    # whose database path is unwritable, or whose generated data is missing,
    # must still boot so /health answers and /ready reports the real problem.
    # Failing the process here would turn a diagnosable condition into a
    # restart loop.
    try:
        initialize_database()
        initialize_workflow_store()
    except Exception as exc:  # noqa: BLE001 - startup must not crash on a broken dependency
        logger.error("startup_database_failed", extra={"detail": type(exc).__name__})
    try:
        ensure_workflow_items()
    except Exception as exc:  # noqa: BLE001
        # A deployment without generated data must still boot so /health and
        # /ready can report the condition; data endpoints return 503.
        logger.warning("startup_data_unavailable", extra={"detail": type(exc).__name__})
    yield
    # Graceful shutdown: release pooled database connections so a rolling
    # restart does not leave the server draining dangling sessions.
    from app.core.database import close_postgres_pool, is_postgres

    if is_postgres():
        close_postgres_pool()


app = FastAPI(
    title="FORTIFY",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.include_router(dashboard_router)
app.include_router(workflow_router)
app.include_router(ingestion_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

RATE_LIMITER = build_rate_limiter()


@app.middleware("http")
async def observe_requests(request: Request, call_next):
    """Assign a correlation id, enforce the request budget, time the handler."""
    request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:16]
    request.state.request_id = request_id
    started = time.perf_counter()

    if RATE_LIMITER is not None and request.url.path.startswith("/api/"):
        client = request.client.host if request.client else "unknown"
        allowed, remaining = RATE_LIMITER.allow(client)
        if not allowed:
            METRICS.increment("http_requests_total", status="429")
            logger.warning("rate_limited", extra={"path": request.url.path, "request_id": request_id})
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please retry shortly."},
                headers={"Retry-After": "60", "X-Request-Id": request_id},
            )

    try:
        response = await call_next(request)
    except Exception:
        METRICS.increment("http_requests_total", status="500")
        logger.exception("unhandled_exception", extra={"path": request.url.path, "request_id": request_id})
        raise

    duration = time.perf_counter() - started
    METRICS.increment("http_requests_total", status=str(response.status_code))
    METRICS.observe("http_request_seconds", duration, path=request.url.path)
    response.headers["X-Request-Id"] = request_id
    from app.observability import redact as redact_log_value

    logger.info(
        "request",
        extra={
            "request_id": request_id,
            "method": request.method,
            # Redact at the call site, not only in the formatter: the raw
            # LogRecord must not carry person identifiers either.
            "path": redact_log_value(request.url.path),
            "status": response.status_code,
            "duration_ms": round(duration * 1000, 2),
        },
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Fail closed with a generic message and a correlation id.

    The exception text is never returned to the client: pandas and SQLite
    messages can carry table contents, file paths and query fragments. It is
    logged instead, correlated by ``X-Request-Id``.
    """
    request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex[:16]
    from app.observability import redact as redact_log_value

    logger.error(
        "unhandled_exception",
        extra={"request_id": request_id, "path": redact_log_value(request.url.path)},
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal error occurred while processing this request.",
            "request_id": request_id,
        },
        headers={"X-Request-Id": request_id},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Give every error response the same envelope: ``{"detail": "<string>"}``.

    FastAPI's default 422 body puts a list in ``detail``, which forces every
    client to special-case validation failures. The field-level information is
    preserved under ``validation_errors``; nothing here echoes request *values*
    back, only field names and what was wrong with them.
    """
    errors = [
        {"field": ".".join(str(part) for part in error.get("loc", [])), "message": error.get("msg", "")}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"detail": "Request validation failed.", "validation_errors": errors},
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is running and able to answer.

    Deliberately dependency-free. A liveness probe that failed on a missing
    artifact would cause Kubernetes to restart an otherwise healthy process.
    """
    return {"status": "ok", "service": "FORTIFY", "version": APP_VERSION}


def _model_readiness() -> dict[str, object]:
    """Model readiness: artifact compatibility, explicitly separated from
    system health and data readiness so a deployment can never present a
    healthy process as a trustworthy model."""
    from app.ml.model_compat import verify as verify_compatibility

    artifacts = ROOT_ARTIFACTS / "phase4" / "model_metadata.json"
    card = ROOT_ARTIFACTS / "phase5" / "model_card.json"
    features = DATA_DIR / "person_day_features_baseline.csv"
    if not artifacts.exists():
        return {"ready": False, "reason": "model metadata missing"}
    compat = verify_compatibility(features, artifacts, card if card.exists() else None)
    failed = [c["check"] for c in compat.checks if not c["ok"]]
    registry = None
    registry_path = ROOT_ARTIFACTS / "model_registry.json"
    if registry_path.exists():
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8")).get("current", {}).get("model_id")
        except json.JSONDecodeError:
            registry = None
    return {"ready": compat.compatible, "failed_checks": failed,
            "checks_run": len(compat.checks), "promoted_model_id": registry}


@app.get("/ready")
def ready() -> JSONResponse:
    """Readiness, in three explicitly separated layers:

    * system  — the process can reach its database;
    * data    — the artifacts exist and pass the data-quality gate (invalid
      records never become welfare evidence, so data-quality errors block
      readiness); staleness is measured against the configured feed cadence,
      not wall-clock (the deterministic demo world has no feed);
    * model   — the artifact set passes the compatibility gate.

    The deployment is ready only when all three are; a stale or invalid data
    source therefore shows as not-ready rather than serving degraded welfare
    evidence silently.
    """
    missing = [name for name in REQUIRED_ARTIFACTS if not (DATA_DIR / name).exists()]
    db_ok = check_database()
    quality = summarize(audit_data_quality(DATA_DIR))
    data_ready = (not missing) and quality["ok"]
    model = _model_readiness()
    ready_now = db_ok and data_ready and bool(model["ready"])
    body: dict[str, object] = {
        "ready": ready_now,
        "version": APP_VERSION,
        "system": {"database": "ok" if db_ok else "unavailable"},
        "data": {
            "artifacts": "ok" if not missing else "missing",
            "data_quality": "ok" if quality["ok"] else "errors",
            "missing_artifacts": missing,
            "quality": quality,
        },
        "model": model,
    }
    if not ready_now:
        body["remedy"] = (
            "Run `python scripts/build_all.py` to regenerate the dataset and "
            "artifacts. Data-quality errors must be resolved before serving."
        )
    return JSONResponse(status_code=200 if ready_now else 503, content=body)


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    """Prometheus text exposition: request counters plus operational gauges.

    Gauges are aggregate operational facts (queue size, follow-up backlog,
    data freshness). No person-level welfare information is ever exported.
    """
    gauges: list[str] = []
    try:
        queue_path = DATA_DIR / "review_queue.csv"
        if queue_path.exists():
            import pandas as pd

            queue = pd.read_csv(queue_path, usecols=["case_created"])
            created = queue["case_created"].astype(str).str.lower().isin(("true", "1")).sum()
            gauges.append(f"fortify_review_queue_total_cases {int(created)}")
    except Exception:  # noqa: BLE001 - metrics must never break scraping
        pass
    try:
        from app.core.database import connect as db_connect

        with db_connect() as conn:
            backlog = conn.execute(
                "SELECT COUNT(*) FROM workflow_followups WHERE status IN ('SCHEDULED','DUE')"
            ).fetchone()[0]
            open_cases = conn.execute(
                "SELECT COUNT(*) FROM workflow_items WHERE workflow_state NOT IN ('CLOSED','DISMISSED','COMPLETED')"
            ).fetchone()[0]
        gauges.append(f"fortify_followup_open_items {int(backlog)}")
        gauges.append(f"fortify_open_cases {int(open_cases)}")
    except Exception:  # noqa: BLE001
        pass
    return METRICS.render() + (chr(10).join(gauges) + chr(10) if gauges else "")


@app.get("/version")
def version() -> dict[str, str]:
    return {"service": "FORTIFY", "version": APP_VERSION}