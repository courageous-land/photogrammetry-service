"""
Integration tests for API endpoints using FastAPI TestClient.

GCP services are mocked so tests run without credentials.
"""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_UUID = "00000000-0000-4000-a000-000000000001"
FAKE_UUID_MISSING = "00000000-0000-4000-a000-ffffffffffff"


def _make_project(project_id: str = FAKE_UUID, status: str = "created", **overrides):
    now = datetime.now(UTC).isoformat()
    base = {
        "project_id": project_id,
        "name": "Test Project",
        "description": None,
        "user_id": None,
        "status": status,
        "progress": 0,
        "files": [],
        "outputs": [],
        "error_message": None,
        "created_at": now,
        "updated_at": now,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_services(monkeypatch):
    """Patch service singletons before the FastAPI app is imported."""
    mock_storage = MagicMock()
    mock_batch = MagicMock()
    mock_pubsub = MagicMock()
    mock_processor = MagicMock()

    # Make service methods async
    mock_storage.create_project = AsyncMock()
    mock_storage.get_project = AsyncMock()
    mock_storage.update_project = AsyncMock()
    mock_storage.list_projects = AsyncMock()
    mock_storage.get_uploaded_files = AsyncMock()
    mock_storage.generate_upload_url = AsyncMock()
    mock_storage.generate_download_url = AsyncMock()
    mock_pubsub.publish_project_created = AsyncMock(return_value="msg-1")
    mock_pubsub.publish_project_processing_started = AsyncMock(return_value="msg-2")
    mock_processor.start_processing = AsyncMock()
    mock_batch.get_job_status = AsyncMock()

    # Also mock firestore_client and uploads_bucket for health check
    mock_storage.firestore_client = MagicMock()
    mock_storage.uploads_bucket = MagicMock()

    # Patch the services module
    with (
        patch("services.storage_service", mock_storage),
        patch("services.batch_service", mock_batch),
        patch("services.pubsub_service", mock_pubsub),
        patch("services.processor_service", mock_processor),
        patch("routers.projects.storage_service", mock_storage),
        patch("routers.projects.batch_service", mock_batch),
        patch("routers.projects.pubsub_service", mock_pubsub),
        patch("routers.projects.processor_service", mock_processor),
    ):
        yield {
            "storage": mock_storage,
            "batch": mock_batch,
            "pubsub": mock_pubsub,
            "processor": mock_processor,
        }


@pytest.fixture()
async def client(mock_services):
    """Async test client."""
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHealthEndpoints:
    @pytest.mark.asyncio
    async def test_root(self, client):
        resp = await client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_health_all_up(self, client, mock_services):
        mock_services["storage"].firestore_client.collection.return_value.limit.return_value.get.return_value = []
        mock_services["storage"].uploads_bucket.exists.return_value = True

        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["components"]["api"] == "up"

    @pytest.mark.asyncio
    async def test_health_degraded(self, client, mock_services):
        mock_services["storage"].firestore_client.collection.return_value.limit.return_value.get.side_effect = Exception("down")
        mock_services["storage"].uploads_bucket.exists.return_value = True

        resp = await client.get("/health")
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["components"]["firestore"] == "down"


class TestCreateProject:
    @pytest.mark.asyncio
    async def test_create_success(self, client, mock_services):
        project = _make_project()
        mock_services["storage"].create_project.return_value = project

        resp = await client.post("/projects", json={"name": "My Project"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == FAKE_UUID
        assert data["status"] == "created"

    @pytest.mark.asyncio
    async def test_create_missing_name(self, client, mock_services):
        resp = await client.post("/projects", json={})
        assert resp.status_code == 422  # Pydantic validation


class TestListProjects:
    @pytest.mark.asyncio
    async def test_list_empty(self, client, mock_services):
        mock_services["storage"].list_projects.return_value = []

        resp = await client.get("/projects")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_with_results(self, client, mock_services):
        mock_services["storage"].list_projects.return_value = [_make_project()]

        resp = await client.get("/projects")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestGetProjectStatus:
    @pytest.mark.asyncio
    async def test_not_found(self, client, mock_services):
        mock_services["storage"].get_project.return_value = None

        resp = await client.get(f"/projects/{FAKE_UUID_MISSING}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_project(self, client, mock_services):
        mock_services["storage"].get_project.return_value = _make_project()

        resp = await client.get(f"/projects/{FAKE_UUID}")
        assert resp.status_code == 200
        assert resp.json()["project_id"] == FAKE_UUID


class TestFinalizeUpload:
    @pytest.mark.asyncio
    async def test_no_files_uploaded(self, client, mock_services):
        mock_services["storage"].get_project.return_value = _make_project()
        mock_services["storage"].get_uploaded_files.return_value = []

        resp = await client.post(f"/projects/{FAKE_UUID}/finalize-upload")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_finalize_success(self, client, mock_services):
        mock_services["storage"].get_project.return_value = _make_project()
        mock_services["storage"].get_uploaded_files.return_value = ["image1.jpg", "image2.jpg"]
        mock_services["storage"].update_project.return_value = _make_project(status="pending")

        resp = await client.post(f"/projects/{FAKE_UUID}/finalize-upload")
        assert resp.status_code == 200
        assert resp.json()["files_count"] == 2


class TestStartProcessing:
    @pytest.mark.asyncio
    async def test_success(self, client, mock_services):
        mock_services["processor"].start_processing.return_value = {
            "success": True,
            "message": "Processing started. Job: job-1",
            "job_info": {"job_id": "job-1", "machine_type": "n2-standard-4", "file_count": 10},
        }
        mock_services["storage"].get_project.return_value = _make_project(status="processing")

        resp = await client.post(f"/projects/{FAKE_UUID}/process")
        assert resp.status_code == 200
        assert resp.json()["status"] == "processing"

    @pytest.mark.asyncio
    async def test_not_found(self, client, mock_services):
        mock_services["processor"].start_processing.return_value = {
            "success": False,
            "error": "Project not found",
        }

        resp = await client.post(f"/projects/{FAKE_UUID_MISSING}/process")
        assert resp.status_code == 404


class TestGetResult:
    @pytest.mark.asyncio
    async def test_not_found(self, client, mock_services):
        mock_services["storage"].get_project.return_value = None

        resp = await client.get(f"/projects/{FAKE_UUID_MISSING}/result")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_outputs(self, client, mock_services):
        project = _make_project(
            status="completed",
            outputs=[{"type": "orthophoto", "filename": "orthophoto.tif", "size_mb": 150}],
        )
        mock_services["storage"].get_project.return_value = project
        mock_services["storage"].generate_download_url.return_value = "https://signed-url"

        resp = await client.get(f"/projects/{FAKE_UUID}/result")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["outputs"]) == 1
        assert len(data["download_urls"]) == 1
