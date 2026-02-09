"""
Processor Service

Orchestrates the photogrammetry processing workflow.
Validates projects and dispatches processing jobs to Cloud Batch.
"""
from typing import Optional, Dict, Any

from models import ProjectStatus


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
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Start processing a project.
        
        Args:
            project_id: Project ID to process
            options: Processing options (ortho_quality, generate_dtm, multispectral)
        
        Returns:
            Dict with success status and message
        """
        # Get project
        project = await self.storage.get_project(project_id)
        if not project:
            return {
                "success": False,
                "error": "Project not found"
            }
        
        # Validate status
        current_status = project.get("status")
        if current_status not in [ProjectStatus.PENDING.value, ProjectStatus.UPLOADING.value]:
            if current_status == ProjectStatus.PROCESSING.value:
                return {
                    "success": False,
                    "error": "Project is already being processed"
                }
            if current_status == ProjectStatus.COMPLETED.value:
                return {
                    "success": False,
                    "error": "Project has already been processed"
                }
        
        # Check for uploaded files
        uploaded_files = await self.storage.get_uploaded_files(project_id)
        if not uploaded_files:
            return {
                "success": False,
                "error": "No images uploaded"
            }
        
        # Count files for machine sizing
        file_count = len(uploaded_files)
        
        # Update status to processing
        await self.storage.update_project(project_id, {
            "status": ProjectStatus.PROCESSING.value,
            "progress": 0,
            "files_count": file_count
        })
        
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
            # Revert status on error
            await self.storage.update_project(project_id, {
                "status": ProjectStatus.FAILED.value,
                "error_message": str(e)
            })
            
            return {
                "success": False,
                "error": f"Failed to create processing job: {str(e)}"
            }
