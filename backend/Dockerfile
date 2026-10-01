# FORTIFY backend — FastAPI API + deterministic offline pipeline in one image.
#
# Build from the REPOSITORY ROOT (the runtime resolves data/artifacts paths
# relative to the repo layout, so the image mirrors it):
#
#   docker build -f backend/Dockerfile -t fortify-backend .
#
# Run the API:            uvicorn entrypoint below (port 8000)
# Regenerate demo data:   docker run fortify-backend python scripts/build_all.py
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install pinned dependencies first so source changes keep the layer cache.
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY scripts /app/scripts

# Unprivileged runtime user. The app only writes under /app/data (SQLite DB,
# audit log) and /app/artifacts (models/reports) — mount volumes there.
RUN useradd --create-home --uid 10001 fortify \
    && mkdir -p /app/data/generated /app/data/runtime /app/artifacts \
    && chown -R fortify:fortify /app/data /app/artifacts
USER fortify

EXPOSE 8000

# Configuration via FORTIFY_* environment variables — see backend/.env.example.
# The default SQLite URL points inside the read-only image, so deployments
# must set FORTIFY_DATABASE_URL to a path on a mounted volume.
# Liveness for orchestrators: depends on nothing but the process itself.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3     CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"]

CMD ["uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000"]
