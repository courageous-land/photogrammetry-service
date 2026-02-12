"""
Cloud Batch Service

Handles creation and management of photogrammetry processing jobs on Google Cloud Batch.
Each job processes a single project using OpenDroneMap in a dedicated VM.

Infrastructure parameters (machine tiers, disk sizing, zones, retries, etc.) are
owned by Pulumi stack config and injected via environment variables.
The only domain logic here is the selection algorithm and disk formula.
"""
import asyncio
import json
import os
from datetime import datetime
from typing import Any

from google.cloud import batch_v1

# ---------------------------------------------------------------------------
# Environment contract helpers
# ---------------------------------------------------------------------------

def require_env(name: str) -> str:
    """Read required environment variable."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} environment variable is required")
    return value


def parse_float_env(name: str) -> float:
    """Parse a required float environment variable."""
    raw = require_env(name)
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got '{raw}'") from exc


def parse_int_env(name: str) -> int:
    """Parse a required int environment variable."""
    raw = require_env(name)
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got '{raw}'") from exc
    if value < 0:
        raise ValueError(f"{name} must be >= 0")
    return value


def parse_allowed_zones(raw_zones: str) -> list[str]:
    """Parse comma-separated zone names into Batch location format."""
    zones = [zone.strip() for zone in raw_zones.split(",") if zone.strip()]
    if not zones:
        raise ValueError("BATCH_ALLOWED_ZONES must contain at least one zone")
    return [zone if zone.startswith("zones/") else f"zones/{zone}" for zone in zones]


def parse_provisioning_model(raw_value: str):
    """Parse Batch provisioning model enum value."""
    normalized = raw_value.strip().upper()
    model_map = {
        "STANDARD": batch_v1.AllocationPolicy.ProvisioningModel.STANDARD,
    }
    spot_model = getattr(batch_v1.AllocationPolicy.ProvisioningModel, "SPOT", None)
    if spot_model is not None:
        model_map["SPOT"] = spot_model

    model = model_map.get(normalized)
    if model is None:
        allowed = ", ".join(sorted(model_map.keys()))
        raise ValueError(
            f"BATCH_PROVISIONING_MODEL invalid value '{raw_value}'. Allowed: {allowed}"
        )
    return model


def parse_log_destination(raw_value: str):
    """Parse Batch log destination enum value."""
    dest_map = {
        "CLOUD_LOGGING": batch_v1.LogsPolicy.Destination.CLOUD_LOGGING,
        "PATH": batch_v1.LogsPolicy.Destination.PATH,
    }
    dest = dest_map.get(raw_value.strip().upper())
    if dest is None:
        allowed = ", ".join(sorted(dest_map.keys()))
        raise ValueError(
            f"BATCH_LOG_DESTINATION invalid value '{raw_value}'. Allowed: {allowed}"
        )
    return dest


def parse_machine_tiers(raw_json: str) -> list[dict[str, Any]]:
    """Parse machine tiers JSON from infra config."""
    try:
        tiers = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError("BATCH_MACHINE_TIERS must be valid JSON") from exc

    if not isinstance(tiers, list) or len(tiers) == 0:
        raise ValueError("BATCH_MACHINE_TIERS must be a non-empty array")

    for i, tier in enumerate(tiers):
        for key in ("maxImages", "machineType", "cpuMilli", "memoryMib"):
            if key not in tier:
                raise ValueError(f"BATCH_MACHINE_TIERS[{i}] missing required key '{key}'")

    # Sort ascending by maxImages for selection algorithm
    tiers.sort(key=lambda t: t["maxImages"])
    return tiers


# ---------------------------------------------------------------------------
# Domain logic (ODM sizing — stays in code)
# ---------------------------------------------------------------------------

def select_machine_tier(
    file_count: int,
    tiers: list[dict[str, Any]],
) -> tuple[str, int, int]:
    """
    Select the best machine tier for the given file count.

    Algorithm: pick the first tier whose maxImages >= file_count.
    If file_count exceeds all tiers, use the largest.

    This is domain knowledge (ODM workload characteristics).
    The tiers themselves are infrastructure config.

    Returns:
        Tuple of (machine_type, cpu_milli, memory_mib)
    """
    for tier in tiers:
        if file_count <= tier["maxImages"]:
            return (tier["machineType"], tier["cpuMilli"], tier["memoryMib"])

    # Exceeds all tiers — use the largest
    largest = tiers[-1]
    return (largest["machineType"], largest["cpuMilli"], largest["memoryMib"])


def calculate_disk_size(
    file_count: int,
    avg_image_size_mb: float,
    safety_margin: float,
    min_boot_disk_mb: int,
) -> int:
    """
    Calculate required disk size based on number of images.

    Formula (domain knowledge — how ODM uses disk):
    - Input: file_count * avg_image_size_mb
    - ODM temporaries + outputs: ~6x input
    - Apply safety_margin
    - Enforce min_boot_disk_mb floor

    Args are infra-owned parameters; formula is domain logic.

    Returns:
        Disk size in MiB
    """
    input_size_mb = file_count * avg_image_size_mb
    total_processing_mb = input_size_mb * 6
    total_with_margin = int(total_processing_mb * safety_margin)
    return max(total_with_margin, min_boot_disk_mb)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class BatchService:
    """
    Service for creating jobs on Cloud Batch.
    Each job processes one photogrammetry project.

    All infrastructure parameters are read from environment variables
    injected by Pulumi via Cloud Run configuration.
    """

    def __init__(self):
        # GCP identity
        self.project_id = require_env("GCP_PROJECT")
        self.region = require_env("GCP_REGION")

        # Worker config (infra-owned)
        self.worker_image = require_env("WORKER_IMAGE")
        self.worker_service_account = require_env("WORKER_SERVICE_ACCOUNT")
        self.worker_command = require_env("BATCH_WORKER_COMMAND").split(",")

        # Resource references (infra-owned)
        self.uploads_bucket_name = require_env("UPLOADS_BUCKET")
        self.outputs_bucket_name = require_env("OUTPUTS_BUCKET")
        self.pubsub_topic = require_env("PUBSUB_TOPIC")

        # Batch policies (infra-owned)
        self.allowed_locations = parse_allowed_zones(require_env("BATCH_ALLOWED_ZONES"))
        self.max_run_duration = require_env("BATCH_MAX_RUN_DURATION")
        self.max_retry_count = parse_int_env("BATCH_MAX_RETRY_COUNT")
        self.provisioning_model = parse_provisioning_model(
            require_env("BATCH_PROVISIONING_MODEL")
        )
        self.log_destination = parse_log_destination(require_env("BATCH_LOG_DESTINATION"))

        # Capacity planning (infra-owned)
        self.machine_tiers = parse_machine_tiers(require_env("BATCH_MACHINE_TIERS"))
        self.min_boot_disk_mb = parse_int_env("BATCH_MIN_BOOT_DISK_MB")
        self.disk_safety_margin = parse_float_env("BATCH_DISK_SAFETY_MARGIN")
        self.avg_image_size_mb = parse_float_env("BATCH_AVG_IMAGE_SIZE_MB")

        self.client = batch_v1.BatchServiceClient()

    async def create_processing_job(
        self,
        project_id: str,
        file_count: int,
        options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Create a Cloud Batch job to process the project.
        Machine type and disk size are automatically selected based on file count
        using infra-defined tiers and domain-owned formulas.
        """
        job_name = f"photogrammetry-{project_id[:8]}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # Domain logic: select tier and compute disk
        machine_type, cpu_milli, memory_mib = select_machine_tier(
            file_count, self.machine_tiers
        )
        disk_size_mib = calculate_disk_size(
            file_count,
            self.avg_image_size_mb,
            self.disk_safety_margin,
            self.min_boot_disk_mb,
        )

        # Container configuration
        container = batch_v1.Runnable.Container(
            image_uri=self.worker_image,
            commands=self.worker_command,
            entrypoint="",
        )

        runnable = batch_v1.Runnable(container=container)

        # VM resources — dynamically sized based on workload
        resources = batch_v1.ComputeResource(
            cpu_milli=cpu_milli,
            memory_mib=memory_mib,
            boot_disk_mib=disk_size_mib
        )

        # Processing options (user input per project)
        odm_options = options or {}
        ortho_quality = odm_options.get("ortho_quality", "medium")
        generate_dtm = odm_options.get("generate_dtm", False)
        multispectral = odm_options.get("multispectral", False)

        # Task specification
        task_spec = batch_v1.TaskSpec(
            runnables=[runnable],
            compute_resource=resources,
            max_retry_count=self.max_retry_count,
            max_run_duration=self.max_run_duration,
            environment=batch_v1.Environment(
                variables={
                    "PROJECT_ID": project_id,
                    "GCP_PROJECT": self.project_id,
                    "UPLOADS_BUCKET": self.uploads_bucket_name,
                    "OUTPUTS_BUCKET": self.outputs_bucket_name,
                    "PUBSUB_TOPIC": self.pubsub_topic,
                    "ORTHO_QUALITY": ortho_quality,
                    "GENERATE_DTM": "true" if generate_dtm else "false",
                    "MULTISPECTRAL": "true" if multispectral else "false",
                }
            )
        )

        # Task group (single task per job)
        task_group = batch_v1.TaskGroup(
            task_count=1,
            task_spec=task_spec
        )

        # Allocation policy
        allocation_policy = batch_v1.AllocationPolicy(
            instances=[
                batch_v1.AllocationPolicy.InstancePolicyOrTemplate(
                    policy=batch_v1.AllocationPolicy.InstancePolicy(
                        machine_type=machine_type,
                        provisioning_model=self.provisioning_model,
                    )
                )
            ],
            location=batch_v1.AllocationPolicy.LocationPolicy(
                allowed_locations=self.allowed_locations
            ),
            service_account=batch_v1.ServiceAccount(
                email=self.worker_service_account
            )
        )

        # Create job
        job = batch_v1.Job(
            task_groups=[task_group],
            allocation_policy=allocation_policy,
            labels={
                "project-id": project_id[:60],
                "type": "photogrammetry",
                "file-count": str(min(file_count, 9999)),
                "machine-type": machine_type.replace("-", "_")
            },
            logs_policy=batch_v1.LogsPolicy(
                destination=self.log_destination
            )
        )

        # Request to create job
        request = batch_v1.CreateJobRequest(
            parent=f"projects/{self.project_id}/locations/{self.region}",
            job_id=job_name,
            job=job
        )

        result = await asyncio.to_thread(self.client.create_job, request=request, timeout=60)

        return {
            "job_name": result.name,
            "job_id": job_name,
            "status": result.status.state.name,
            "machine_type": machine_type,
            "cpu_cores": cpu_milli // 1000,
            "memory_gb": memory_mib // 1024,
            "disk_gb": disk_size_mib // 1024,
            "file_count": file_count,
            "created_at": datetime.now().isoformat()
        }

    async def get_job_status(self, job_name: str) -> dict[str, Any]:
        """Get job status."""
        request = batch_v1.GetJobRequest(name=job_name)
        job = await asyncio.to_thread(self.client.get_job, request=request, timeout=10)

        return {
            "job_name": job.name,
            "status": job.status.state.name,
            "status_events": [
                {
                    "type": e.type_,
                    "description": e.description,
                    "timestamp": e.event_time.isoformat() if e.event_time else None
                }
                for e in job.status.status_events
            ]
        }
