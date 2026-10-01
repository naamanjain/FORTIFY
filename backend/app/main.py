from __future__ import annotations

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
from app.api.routes.workflow import router as workflow_router
from app.core.config import settings
from app.core.database import check_database, initialize_database
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


app = FastAPI(
    title="FORTIFY",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.include_router(dashboard_router)
app.include_router(workflow_router)

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
    logger.info(
        "request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
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
    logger.error(
        "unhandled_exception",
        extra={"request_id": request_id, "path": request.url.path},
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


@app.get("/ready")
def ready() -> JSONResponse:
    """Readiness: the process can actually serve data requests.

    Checks the database, the generated artifacts and the internal consistency
    of those artifacts, and returns 503 when the deployment cannot serve so
    traffic is routed elsewhere rather than turning every request into an
    error. Data-quality errors make the deployment not-ready: welfare evidence
    must not be drawn from broken input.
    """
    missing = [name for name in REQUIRED_ARTIFACTS if not (DATA_DIR / name).exists()]
    db_ok = check_database()
    quality = summarize(audit_data_quality(DATA_DIR))
    ready_now = db_ok and not missing and quality["ok"]
    body: dict[str, object] = {
        "ready": ready_now,
        "version": APP_VERSION,
        "checks": {
            "database": "ok" if db_ok else "unavailable",
            "artifacts": "ok" if not missing else "missing",
            "data_quality": "ok" if quality["ok"] else "errors",
        },
        "missing_artifacts": missing,
        "data_quality": quality,
    }
    if not ready_now:
        body["remedy"] = (
            "Run `python scripts/build_all.py` to generate the demonstration dataset. "
            "If data quality reports errors, resolve those before serving."
        )
    return JSONResponse(status_code=200 if ready_now else 503, content=body)


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    """Prometheus text exposition of the in-process counters."""
    return METRICS.render()


@app.get("/version")
def version() -> dict[str, str]:
    return {"service": "FORTIFY", "version": APP_VERSION}