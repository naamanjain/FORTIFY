from __future__ import annotations

import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import initialize_database
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.workflow import router as workflow_router
from app.services.workflow import DataUnavailable, ensure_workflow_items, initialize_workflow_store


@asynccontextmanager
async def lifespan(application: FastAPI):
    initialize_database()
    initialize_workflow_store()
    try:
        ensure_workflow_items()
    except DataUnavailable as exc:
        # A deployment without generated data must still boot so /health and
        # governance endpoints respond; data endpoints return 503 with guidance.
        print(f"WARNING: {exc}", file=sys.stderr)
    yield


app = FastAPI(title="FORTIFY", version="0.1.0", lifespan=lifespan)

app.include_router(dashboard_router)
app.include_router(workflow_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "FORTIFY"}
