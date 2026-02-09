"""
Projects Router

REST API endpoints for photogrammetry project management.
Handles project creation, file uploads, processing, and results.
"""
from fastapi import APIRouter, HTTPException, Query, Request
from typing import Optional, List
from datetime import datetime

from models import (
    CreateProjectRequest,
    CreateProjectResponse,
    UploadUrlRequest,
    UploadUrlResponse,
    ProcessRequest,
    ProcessResponse,
    ProjectStatusResponse,
    ProjectResultResponse,
    ProjectStatus,
    ErrorResponse
)
from services import storage_service, processor_service


router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post(
    "",
    response_model=CreateProjectResponse,
    responses={400: {"model": ErrorResponse}},
    summary="Create a new project",
    description="Creates a new photogrammetry project and returns its ID for subsequent operations."
)
async def create_project(request: CreateProjectRequest):
    """Create a new photogrammetry project."""
    project = await storage_service.create_project(
        name=request.name,
        description=request.description,
        user_id=request.user_id
    )
    
    return CreateProjectResponse(
        project_id=project["project_id"],
        name=project["name"],
        status=ProjectStatus(project["status"]),
        created_at=datetime.fromisoformat(project["created_at"])
    )


@router.get(
    "",
    response_model=List[ProjectStatusResponse],
    summary="List projects",
    description="Lists all projects, optionally filtered by user_id."
)
async def list_projects(
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of results")
):
    """List projects."""
    projects = await storage_service.list_projects(user_id=user_id, limit=limit)
    
    return [
        ProjectStatusResponse(
            project_id=p["project_id"],
            name=p["name"],
            status=ProjectStatus(p["status"]),
            progress=p.get("progress", 0),
            files_count=len(p.get("files", [])),
            created_at=datetime.fromisoformat(p["created_at"]),
            updated_at=datetime.fromisoformat(p["updated_at"]),
            error_message=p.get("error_message")
        )
        for p in projects
    ]


@router.get(
    "/{project_id}",
    response_model=ProjectStatusResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Get project status",
    description="Returns the current status of a project. Use for polling during processing."
)
async def get_project_status(project_id: str):
    """Get project status."""
    project = await storage_service.get_project(project_id)
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    return ProjectStatusResponse(
        project_id=project["project_id"],
        name=project["name"],
        status=ProjectStatus(project["status"]),
        progress=project.get("progress", 0),
        files_count=len(project.get("files", [])),
        created_at=datetime.fromisoformat(project["created_at"]),
        updated_at=datetime.fromisoformat(project["updated_at"]),
        error_message=project.get("error_message")
    )


@router.post(
    "/{project_id}/upload-url",
    response_model=UploadUrlResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Generate upload URL",
    description="""
    Generates a URL for direct file upload to Cloud Storage.
    
    Two modes available:
    - **Resumable** (default): For large files. Allows resuming interrupted uploads.
      Requires file_size. Returns session URL that accepts chunked uploads.
    - **Simple**: For small files (<50MB). Signed URL with direct PUT.
    
    The client uploads directly to Cloud Storage, bypassing the API.
    """
)
async def get_upload_url(project_id: str, body: UploadUrlRequest, request: Request):
    """Generate URL for file upload."""
    use_resumable = body.resumable and body.file_size is not None
    
    # Extract origin for CORS
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin:
        origin = origin.split("?")[0].rstrip("/")
    
    result = await storage_service.generate_upload_url(
        project_id=project_id,
        filename=body.filename,
        file_size=body.file_size,
        content_type=body.content_type or "application/octet-stream",
        resumable=use_resumable,
        origin=origin
    )
    
    if not result:
        raise HTTPException(status_code=404, detail="Project not found")
    
    return UploadUrlResponse(
        upload_url=result["upload_url"],
        file_id=result["file_id"],
        upload_type=result.get("upload_type", "simple"),
        chunk_size=result.get("chunk_size"),
        expires_in=3600
    )


@router.post(
    "/{project_id}/finalize-upload",
    responses={404: {"model": ErrorResponse}},
    summary="Finalize upload",
    description="Finalizes the upload process and updates status to PENDING. Call when all uploads are complete."
)
async def finalize_upload(project_id: str):
    """Finalize upload and update status to PENDING."""
    project = await storage_service.get_project(project_id)
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Count files in bucket
    uploaded_files = await storage_service.get_uploaded_files(project_id)
    files_count = len(uploaded_files)
    
    if files_count == 0:
        raise HTTPException(status_code=400, detail="No files uploaded")
    
    # Update status to PENDING
    await storage_service.update_project(project_id, {
        "status": ProjectStatus.PENDING.value,
        "files_count": files_count
    })
    
    return {
        "success": True,
        "project_id": project_id,
        "files_count": files_count,
        "status": "pending"
    }


@router.post(
    "/{project_id}/process",
    response_model=ProcessResponse,
    responses={404: {"model": ErrorResponse}, 400: {"model": ErrorResponse}},
    summary="Start processing",
    description="""
    Starts photogrammetry processing for the project.
    
    Processing options:
    - **ortho_quality**: low, medium, high (default: medium)
    - **generate_dtm**: Generate Digital Terrain Model (default: false)
    - **multispectral**: Enable multispectral processing (default: false)
    
    Processing runs asynchronously on Cloud Batch.
    """
)
async def start_processing(project_id: str, request: ProcessRequest = None):
    """Start photogrammetry processing."""
    if request is None:
        request = ProcessRequest()
    
    result = await processor_service.start_processing(
        project_id=project_id,
        options=request.options
    )
    
    if not result["success"]:
        if "not found" in result.get("error", "").lower():
            raise HTTPException(status_code=404, detail=result["error"])
        raise HTTPException(status_code=400, detail=result["error"])
    
    project = await storage_service.get_project(project_id)
    
    return ProcessResponse(
        project_id=project_id,
        status=ProjectStatus(project["status"]),
        message=result["message"]
    )


@router.get(
    "/{project_id}/result",
    response_model=ProjectResultResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Get processing results",
    description="Returns processing results. Available only when status is COMPLETED."
)
async def get_project_result(project_id: str):
    """Get project processing results."""
    project = await storage_service.get_project(project_id)
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    outputs = project.get("outputs", [])
    
    # Generate download URLs for outputs
    download_urls = []
    for output in outputs:
        url = await storage_service.generate_download_url(
            project_id=project_id,
            filename=output.get("filename", "")
        )
        if url:
            download_urls.append(url)
    
    return ProjectResultResponse(
        project_id=project_id,
        status=ProjectStatus(project["status"]),
        outputs=outputs,
        download_urls=download_urls
    )
