"""
Cloud Batch Service

Handles creation and management of photogrammetry processing jobs on Google Cloud Batch.
Each job processes a single project using OpenDroneMap in a dedicated VM.

Machine sizing based on: https://www.mdpi.com/2673-7086/3/3/23
"OpenDroneMap: Multi-Platform Performance Analysis" (Gbagir et al., 2023)
"""
import os
from typing import Optional, Dict, Any, Tuple
from datetime import datetime

from google.cloud import batch_v1


# Average image size in MB (drone images typically 8-12 MB)
AVG_IMAGE_SIZE_MB = 9

# Safety margin for disk space (15%)
DISK_SAFETY_MARGIN = 1.15

# Minimum boot disk size in MB (for OS and Docker)
MIN_BOOT_DISK_MB = 50 * 1024  # 50 GB


def get_machine_config(file_count: int) -> Tuple[str, int, int]:
    """
    Determine optimal machine type based on number of images.
    
    Based on research paper findings:
    - 20 cores optimal for ~1000 images, 10 cores slightly slower
    - 64 GB RAM sufficient for ~1000 images
    - 256 GB RAM needed for ~8000 images
    - Adding more than 40 cores shows no improvement
    
    Args:
        file_count: Number of images to process
        
    Returns:
        Tuple of (machine_type, cpu_milli, memory_mib)
    """
    if file_count <= 200:
        # Small datasets - 4 vCPU, 16 GB RAM
        return ("n2-standard-4", 4000, 16 * 1024)
    
    elif file_count <= 500:
        # Medium-small datasets - 8 vCPU, 32 GB RAM
        return ("n2-standard-8", 8000, 32 * 1024)
    
    elif file_count <= 1000:
        # Medium datasets - 8 vCPU, 64 GB RAM (paper: 64GB for ~1000 images)
        return ("n2-highmem-8", 8000, 64 * 1024)
    
    elif file_count <= 2000:
        # Medium-large datasets - 16 vCPU, 128 GB RAM
        return ("n2-highmem-16", 16000, 128 * 1024)
    
    else:
        # Large datasets (2000+) - 32 vCPU, 256 GB RAM (paper: 256GB for ~8000)
        return ("n2-highmem-32", 32000, 256 * 1024)


def calculate_disk_size(file_count: int) -> int:
    """
    Calculate required disk size based on number of images.
    
    Disk usage breakdown:
    - Input images: file_count * 9 MB
    - ODM temporaries: ~3x input size (point clouds, meshes, etc.)
    - Output files: ~2x input size (orthophoto, DSM, DTM, etc.)
    - Total: ~6x input size + 15% safety margin
    
    Args:
        file_count: Number of images to process
        
    Returns:
        Disk size in MiB
    """
    # Calculate base storage needed
    input_size_mb = file_count * AVG_IMAGE_SIZE_MB
    
    # ODM needs approximately 6x input size for all processing stages
    # - Temporary files (feature extraction, matching): ~2x
    # - Point cloud and mesh: ~2x
    # - Final outputs (orthophoto, DEM): ~2x
    total_processing_mb = input_size_mb * 6
    
    # Apply safety margin
    total_with_margin = int(total_processing_mb * DISK_SAFETY_MARGIN)
    
    # Ensure minimum disk size for OS and Docker
    return max(total_with_margin, MIN_BOOT_DISK_MB)


class BatchService:
    """
    Service for creating jobs on Cloud Batch.
    Each job processes one photogrammetry project.
    """
    
    def __init__(self):
        self.project_id = os.environ.get("GCP_PROJECT")
        if not self.project_id:
            raise ValueError("GCP_PROJECT environment variable is required")
        
        self.region = os.environ.get("GCP_REGION", "southamerica-east1")
        self.worker_image = os.environ.get(
            "WORKER_IMAGE", 
            f"{self.region}-docker.pkg.dev/{self.project_id}/photogrammetry/worker:latest"
        )
        self.worker_service_account = os.environ.get(
            "WORKER_SERVICE_ACCOUNT",
            f"photogrammetry-worker@{self.project_id}.iam.gserviceaccount.com"
        )
        
        self.client = batch_v1.BatchServiceClient()
    
    async def create_processing_job(
        self,
        project_id: str,
        file_count: int,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a Cloud Batch job to process the project.
        Machine type and disk size are automatically selected based on file count.
        
        Args:
            project_id: Project ID to process
            file_count: Number of images in the project
            options: ODM processing options
        
        Returns:
            Dict with job information
        """
        job_name = f"photogrammetry-{project_id[:8]}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Get optimal machine configuration based on file count
        machine_type, cpu_milli, memory_mib = get_machine_config(file_count)
        disk_size_mib = calculate_disk_size(file_count)
        
        # Container configuration
        container = batch_v1.Runnable.Container(
            image_uri=self.worker_image,
            commands=["python3", "/worker/main.py"],
            entrypoint="",
        )
        
        runnable = batch_v1.Runnable(container=container)
        
        # VM resources - dynamically sized based on workload
        resources = batch_v1.ComputeResource(
            cpu_milli=cpu_milli,
            memory_mib=memory_mib,
            boot_disk_mib=disk_size_mib
        )
        
        # Processing options
        odm_options = options or {}
        ortho_quality = odm_options.get("ortho_quality", "medium")
        generate_dtm = odm_options.get("generate_dtm", False)
        multispectral = odm_options.get("multispectral", False)
        
        # Task specification
        task_spec = batch_v1.TaskSpec(
            runnables=[runnable],
            compute_resource=resources,
            max_retry_count=2,
            max_run_duration="43200s",  # 12 hours max
            environment=batch_v1.Environment(
                variables={
                    "PROJECT_ID": project_id,
                    "GCP_PROJECT": self.project_id,
                    "UPLOADS_BUCKET": f"{self.project_id}-photogrammetry-uploads",
                    "OUTPUTS_BUCKET": f"{self.project_id}-photogrammetry-outputs",
                    "PUBSUB_TOPIC": "photogrammetry-status",
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
        
        # Allocation policy - machine type selected based on workload
        allocation_policy = batch_v1.AllocationPolicy(
            instances=[
                batch_v1.AllocationPolicy.InstancePolicyOrTemplate(
                    policy=batch_v1.AllocationPolicy.InstancePolicy(
                        machine_type=machine_type,
                        provisioning_model=batch_v1.AllocationPolicy.ProvisioningModel.STANDARD,
                    )
                )
            ],
            location=batch_v1.AllocationPolicy.LocationPolicy(
                allowed_locations=[f"zones/{self.region}-a", f"zones/{self.region}-b"]
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
                "file-count": str(min(file_count, 9999)),  # Label value limit
                "machine-type": machine_type.replace("-", "_")
            },
            logs_policy=batch_v1.LogsPolicy(
                destination=batch_v1.LogsPolicy.Destination.CLOUD_LOGGING
            )
        )
        
        # Request to create job
        request = batch_v1.CreateJobRequest(
            parent=f"projects/{self.project_id}/locations/{self.region}",
            job_id=job_name,
            job=job
        )
        
        result = self.client.create_job(request=request)
        
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
    
    async def get_job_status(self, job_name: str) -> Dict[str, Any]:
        """Get job status."""
        request = batch_v1.GetJobRequest(name=job_name)
        job = self.client.get_job(request=request)
        
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
