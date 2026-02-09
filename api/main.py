"""
Photogrammetry Service API

REST API for photogrammetry processing using OpenDroneMap on Google Cloud Platform.

Architecture:
- Cloud Run: API hosting
- Cloud Storage: Image uploads and processed outputs
- Firestore: Project metadata and status
- Cloud Batch: Processing jobs with OpenDroneMap
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from routers import projects


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management."""
    # Startup
    print("=" * 60)
    print("Photogrammetry Service API - Starting")
    print(f"GCP Project: {os.environ.get('GCP_PROJECT', 'not set')}")
    print(f"Region: {os.environ.get('GCP_REGION', 'not set')}")
    print("=" * 60)
    yield
    # Shutdown
    print("Photogrammetry Service API - Shutting down")


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
    version="1.0.0",
    lifespan=lifespan
)

# CORS - configure allowed origins for production
allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
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
        "version": "1.0.0"
    }


@app.get("/health", tags=["Health"])
async def health():
    """Detailed health check."""
    return {
        "status": "healthy",
        "gcp_project": os.environ.get("GCP_PROJECT"),
        "region": os.environ.get("GCP_REGION"),
        "components": {
            "api": "up",
            "storage": "up",
            "batch": "up"
        }
    }
