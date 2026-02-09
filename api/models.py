from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum
from datetime import datetime


class ProjectStatus(str, Enum):
    CREATED = "created"
    UPLOADING = "uploading"
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    user_id: Optional[str] = None


class CreateProjectResponse(BaseModel):
    project_id: str
    name: str
    status: ProjectStatus
    created_at: datetime


class UploadUrlRequest(BaseModel):
    filename: str = Field(..., min_length=1)
    file_size: Optional[int] = Field(None, description="Tamanho do arquivo em bytes (necessário para resumable)")
    content_type: Optional[str] = Field("image/jpeg", description="Tipo MIME do arquivo")
    resumable: Optional[bool] = Field(True, description="Usar upload resumable (recomendado para arquivos > 5MB)")


class UploadUrlResponse(BaseModel):
    upload_url: str
    file_id: str
    upload_type: str = Field("resumable", description="Tipo: 'resumable' ou 'simple'")
    chunk_size: Optional[int] = Field(None, description="Tamanho recomendado de cada chunk em bytes")
    expires_in: int = 3600


class ProcessingOptions(BaseModel):
    ortho_quality: Optional[str] = Field("medium", pattern="^(low|medium|high)$", description="Qualidade: low, medium, high")
    generate_dtm: Optional[bool] = Field(False, description="Gerar modelo digital de terreno")
    multispectral: Optional[bool] = Field(False, description="Processamento multiespectral")


class ProcessRequest(BaseModel):
    options: Optional[ProcessingOptions] = None


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
    error_message: Optional[str] = None


class ProjectResultResponse(BaseModel):
    project_id: str
    status: ProjectStatus
    outputs: List[dict] = []
    download_urls: List[str] = []


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
