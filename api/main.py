"""
Photogrammetry Service API

REST API for photogrammetry processing using OpenDroneMap on Google Cloud Platform.

Architecture:
- Cloud Run: API hosting
- Cloud Storage: Image uploads and processed outputs
- Firestore: Project metadata and status
- Cloud Batch: Processing jobs with OpenDroneMap
"""
import logging
import os
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import projects

logger = logging.getLogger(__name__)
APP_VERSION = "1.0.0"


def load_allowed_origins() -> list[str]:
    """Load CORS origins from infrastructure-managed environment variable."""
    raw_origins = os.environ.get("ALLOWED_ORIGINS")
    if not raw_origins:
        raise ValueError(
            "ALLOWED_ORIGINS environment variable is required. "
            "Set it via Pulumi Cloud Run configuration."
        )

    origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]
    if not origins:
        raise ValueError("ALLOWED_ORIGINS must contain at least one origin.")

    if "*" in origins and len(origins) > 1:
        raise ValueError("ALLOWED_ORIGINS cannot mix '*' with specific origins.")

    return origins


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management."""
    # Startup
    logger.info("=" * 60)
    logger.info("Photogrammetry Service API - Starting")
    logger.info("GCP Project: %s", os.environ.get("GCP_PROJECT", "not set"))
    logger.info("Region: %s", os.environ.get("GCP_REGION", "not set"))
    logger.info("=" * 60)
    yield
    # Shutdown — release GCP client connections
    from services import batch_service, pubsub_service, storage_service as _ss

    try:
        _ss.storage_client.close()
        _ss.firestore_client.close()
    except Exception as exc:
        logger.warning("Error closing storage/firestore clients: %s", exc)
    try:
        batch_service.client.transport.close()
    except Exception as exc:
        logger.warning("Error closing Batch client: %s", exc)
    try:
        pubsub_service.publisher.transport.close()
    except Exception as exc:
        logger.warning("Error closing PubSub client: %s", exc)

    logger.info("Photogrammetry Service API - Shutting down")


app = FastAPI(
    title="Photogrammetry Service API",
    description="""
## Overview

REST API for photogrammetry processing. Transforms aerial images into orthophotos,
digital surface models (DSM), digital terrain models (DTM), and point clouds.

## Workflow

1. **Create project**: `POST /projects`
2. **Get upload URL**: `POST /projects/{id}/upload-url`
3. **Upload images**: Direct PUT to Cloud Storage URL
4. **Finalize upload**: `POST /projects/{id}/finalize-upload`
5. **Start processing**: `POST /projects/{id}/process`
6. **Poll status**: `GET /projects/{id}`
7. **Get results**: `GET /projects/{id}/result`

## Project Status

| Status | Description |
|--------|-------------|
| `created` | Project created, awaiting uploads |
| `uploading` | Uploads in progress |
| `pending` | Ready for processing |
| `processing` | Processing in progress |
| `completed` | Processing completed |
| `failed` | Processing failed |

## Processing Options

| Option | Values | Description |
|--------|--------|-------------|
| `ortho_quality` | low, medium, high | Orthophoto quality |
| `generate_dtm` | true, false | Generate terrain model |
| `multispectral` | true, false | Multispectral processing |
    """,
    version=APP_VERSION,
    lifespan=lifespan
)

# CORS configuration is controlled by Pulumi stacks
allowed_origins = load_allowed_origins()
allow_credentials = "*" not in allowed_origins

# Store on app.state so routers can validate origins for GCS CORS
app.state.allowed_origins = allowed_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=allow_credentials,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["*"],
)

# Routers
app.include_router(projects.router)


@app.get("/", tags=["Health"])
async def root():
    """Service health check."""
    return {
        "service": "Photogrammetry Service",
        "status": "running",
        "version": APP_VERSION
    }


@app.get("/health", tags=["Health"])
async def health():
    """Detailed health check — verifies connectivity to backend services."""
    from services import storage_service

    components: dict[str, str] = {"api": "up"}

    # Firestore connectivity
    try:
        await asyncio.to_thread(
            storage_service.firestore_client.collection("_health").limit(1).get
        )
        components["firestore"] = "up"
    except Exception as exc:
        logger.warning("Health check: Firestore unreachable — %s", exc)
        components["firestore"] = "down"

    # Cloud Storage connectivity
    try:
        await asyncio.to_thread(storage_service.uploads_bucket.exists)
        components["storage"] = "up"
    except Exception as exc:
        logger.warning("Health check: Cloud Storage unreachable — %s", exc)
        components["storage"] = "down"

    all_up = all(v == "up" for v in components.values())
    return {
        "status": "healthy" if all_up else "degraded",
        "components": components,
    }
