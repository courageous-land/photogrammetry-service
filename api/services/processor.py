"""
Processor Service

Orchestrates the photogrammetry processing workflow.
Validates projects and dispatches processing jobs to Cloud Batch.
"""
import logging
from typing import Any

from models import ProjectStatus

logger = logging.getLogger(__name__)


class ProcessorService:
    """
    Service that orchestrates photogrammetry processing.
    """

    def __init__(self, storage_service, batch_service):
        self.storage = storage_service
        self.batch = batch_service

    async def start_processing(
        self,
        project_id: str,
        options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Start processing a project.

        Uses an atomic status transition to prevent double-processing when
        concurrent requests arrive for the same project.

        Args:
            project_id: Project ID to process
            options: Processing options (ortho_quality, generate_dtm, multispectral)

        Returns:
            Dict with success status and message
        """
        # Check for uploaded files first (read-only, no race concern)
        uploaded_files = await self.storage.get_uploaded_files(project_id)
        if not uploaded_files:
            project = await self.storage.get_project(project_id)
            if not project:
                return {"success": False, "error": "Project not found"}
            return {"success": False, "error": "No images uploaded"}

        file_count = len(uploaded_files)

        # Atomically transition status — only succeeds if current status
        # is PENDING or UPLOADING, preventing double-processing.
        result = await self.storage.transition_status(
            project_id=project_id,
            allowed_from=[
                ProjectStatus.PENDING.value,
                ProjectStatus.UPLOADING.value,
            ],
            new_status=ProjectStatus.PROCESSING.value,
            extra_updates={"progress": 0, "files_count": file_count},
        )

        if result is None:
            return {"success": False, "error": "Project not found"}

        if result.get("__rejected"):
            current = result["current_status"]
            if current == ProjectStatus.PROCESSING.value:
                return {"success": False, "error": "Project is already being processed"}
            if current == ProjectStatus.COMPLETED.value:
                return {"success": False, "error": "Project has already been processed"}
            return {"success": False, "error": f"Cannot process project in status: {current}"}

        # Create batch job with dynamic machine sizing
        try:
            job_info = await self.batch.create_processing_job(
                project_id=project_id,
                file_count=file_count,
                options=options
            )

            # Save job info
            await self.storage.update_project(project_id, {
                "batch_job": job_info
            })

            return {
                "success": True,
                "message": f"Processing started. Job: {job_info['job_id']}",
                "job_info": job_info
            }

        except Exception as e:
            # Log full error server-side; return sanitized message to client
            logger.error("Failed to create batch job for %s: %s", project_id, e)
            await self.storage.update_project(project_id, {
                "status": ProjectStatus.FAILED.value,
                "error_message": "Internal error creating processing job",
            })

            return {
                "success": False,
                "error": "Failed to create processing job"
            }
