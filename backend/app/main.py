from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import initialize_database
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.workflow import router as workflow_router
from app.services.workflow import initialize_workflow_store

app = FastAPI(title="FORTIFY", version="0.1.0")

app.include_router(dashboard_router)
app.include_router(workflow_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    initialize_database()
    initialize_workflow_store()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "FORTIFY"}
