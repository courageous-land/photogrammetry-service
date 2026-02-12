from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ProjectStatus(str, Enum):
    CREATED = "created"
    UPLOADING = "uploading"
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=2048)
    user_id: str | None = Field(None, max_length=128)


class CreateProjectResponse(BaseModel):
    project_id: str
    name: str
    status: ProjectStatus
    created_at: datetime


_ALLOWED_CONTENT_TYPES = frozenset({
    "image/jpeg", "image/png", "image/tiff", "image/gif", "image/webp",
    "application/octet-stream",
})


class UploadUrlRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=1024)
    file_size: int | None = Field(
        None, ge=1, le=5_368_709_120,
        description="Tamanho do arquivo em bytes (1 B – 5 GB, necessário para resumable)",
    )
    content_type: str | None = Field(
        "image/jpeg", max_length=128,
        description="Tipo MIME do arquivo",
    )
    resumable: bool | None = Field(True, description="Usar upload resumable (recomendado para arquivos > 5MB)")


class UploadUrlResponse(BaseModel):
    upload_url: str
    file_id: str
    upload_type: str = Field("resumable", description="Tipo: 'resumable' ou 'simple'")
    chunk_size: int | None = Field(None, description="Tamanho recomendado de cada chunk em bytes")
    expires_in: int = 3600


class ProcessingOptions(BaseModel):
    ortho_quality: str | None = Field("medium", pattern="^(low|medium|high)$", description="Qualidade: low, medium, high")
    generate_dtm: bool | None = Field(False, description="Gerar modelo digital de terreno")
    multispectral: bool | None = Field(False, description="Processamento multiespectral")


class ProcessRequest(BaseModel):
    options: ProcessingOptions | None = None


class ProcessResponse(BaseModel):
    project_id: str
    status: ProjectStatus
    message: str


class ProjectStatusResponse(BaseModel):
    project_id: str
    name: str
    status: ProjectStatus
    progress: int = 0
    files_count: int = 0
    created_at: datetime
    updated_at: datetime
    error_message: str | None = None


class ProjectResultResponse(BaseModel):
    project_id: str
    status: ProjectStatus
    outputs: list[dict] = []
    download_urls: list[str] = []


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
