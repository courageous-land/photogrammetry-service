"""
Shared test fixtures.

Adds the ``api/`` directory to ``sys.path`` so that imports like
``from models import ...`` work outside of the Docker container.

IMPORTANT: Environment variables are set at *session* scope (before collection)
because ``services/__init__.py`` eagerly instantiates GCP clients on import.
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure the api package is importable
API_DIR = str(Path(__file__).resolve().parent.parent / "api")
if API_DIR not in sys.path:
    sys.path.insert(0, API_DIR)

# ---------------------------------------------------------------------------
# Set env vars BEFORE collection (module import time) so that
# services/__init__.py can instantiate without real GCP credentials.
# Individual tests can still override with monkeypatch.
# ---------------------------------------------------------------------------
_ENV_DEFAULTS = {
    "GCP_PROJECT": "test-project",
    "GCP_REGION": "southamerica-east1",
    "UPLOADS_BUCKET": "test-uploads",
    "OUTPUTS_BUCKET": "test-outputs",
    "ALLOWED_ORIGINS": "*",
    "SERVICE_ACCOUNT_EMAIL": "test@test.iam.gserviceaccount.com",
    "WORKER_IMAGE": "gcr.io/test/worker:latest",
    "WORKER_SERVICE_ACCOUNT": "worker@test.iam.gserviceaccount.com",
    "PUBSUB_TOPIC": "test-topic",
    "BATCH_ALLOWED_ZONES": "us-central1-a,us-central1-b",
    "BATCH_MAX_RUN_DURATION": "3600s",
    "BATCH_MAX_RETRY_COUNT": "2",
    "BATCH_PROVISIONING_MODEL": "STANDARD",
    "BATCH_LOG_DESTINATION": "CLOUD_LOGGING",
    "BATCH_WORKER_COMMAND": "python3,/worker/main.py",
    "BATCH_MACHINE_TIERS": (
        '[{"maxImages":200,"machineType":"n2-standard-4","cpuMilli":4000,"memoryMib":16384},'
        '{"maxImages":500,"machineType":"n2-standard-8","cpuMilli":8000,"memoryMib":32768}]'
    ),
    "BATCH_MIN_BOOT_DISK_MB": "51200",
    "BATCH_DISK_SAFETY_MARGIN": "1.15",
    "BATCH_AVG_IMAGE_SIZE_MB": "9",
}

for _key, _value in _ENV_DEFAULTS.items():
    os.environ.setdefault(_key, _value)

# ---------------------------------------------------------------------------
# Mock GCP SDK clients so tests run without credentials.
# This must happen before any service module is imported.
# ---------------------------------------------------------------------------
_mock_credentials = MagicMock()
_mock_credentials.valid = True
_mock_credentials.token = "fake-token"
_mock_credentials.service_account_email = "test@test.iam.gserviceaccount.com"

_patches = [
    patch("google.auth.default", return_value=(_mock_credentials, "test-project")),
    patch("google.cloud.storage.Client"),
    patch("google.cloud.firestore.Client"),
    patch("google.cloud.pubsub_v1.PublisherClient"),
    patch("google.cloud.batch_v1.BatchServiceClient"),
]

for _p in _patches:
    _p.start()
