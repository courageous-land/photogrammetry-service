"""
Storage Service - Google Cloud Platform

Handles all storage operations:
- Cloud Storage: Image uploads and processed outputs
- Firestore: Project metadata and status tracking
"""
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from uuid import uuid4

import google.auth
from google.auth.transport import requests
from google.cloud import storage
from google.cloud import firestore

from models import ProjectStatus


class StorageService:
    """
    Storage service using GCP.
    - Cloud Storage: uploads and outputs
    - Firestore: project metadata
    """
    
    def __init__(self):
        self.project_id = os.environ.get("GCP_PROJECT")
        if not self.project_id:
            raise ValueError("GCP_PROJECT environment variable is required")
        
        self.uploads_bucket_name = os.environ.get(
            "UPLOADS_BUCKET", 
            f"{self.project_id}-photogrammetry-uploads"
        )
        self.outputs_bucket_name = os.environ.get(
            "OUTPUTS_BUCKET", 
            f"{self.project_id}-photogrammetry-outputs"
        )
        
        # GCP credentials
        self.credentials, _ = google.auth.default()
        
        # GCP clients
        self.storage_client = storage.Client(project=self.project_id)
        self.firestore_client = firestore.Client(project=self.project_id)
        
        # References
        self.uploads_bucket = self.storage_client.bucket(self.uploads_bucket_name)
        self.outputs_bucket = self.storage_client.bucket(self.outputs_bucket_name)
        self.projects_collection = self.firestore_client.collection("projects")
        
        # Auth request for token refresh
        self._auth_request = requests.Request()
        
        # Service account email for signing URLs
        self.service_account_email = self._get_service_account_email()
    
    def _get_service_account_email(self) -> str:
        """Get service account email for signing URLs."""
        # 1. Environment variable (recommended for Cloud Run)
        sa_email = os.environ.get("SERVICE_ACCOUNT_EMAIL")
        if sa_email:
            return sa_email
        
        # 2. Credentials attribute
        if hasattr(self.credentials, 'service_account_email') and self.credentials.service_account_email:
            return self.credentials.service_account_email
        
        # 3. Metadata server (Cloud Run/GCE/GKE)
        try:
            import urllib.request
            metadata_url = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email"
            req = urllib.request.Request(metadata_url, headers={"Metadata-Flavor": "Google"})
            with urllib.request.urlopen(req, timeout=2) as response:
                return response.read().decode('utf-8')
        except Exception:
            pass
        
        # 4. Fallback
        return f"photogrammetry-api@{self.project_id}.iam.gserviceaccount.com"
    
    def _get_access_token(self) -> str:
        """Get updated access token for signing URLs."""
        if not self.credentials.valid:
            self.credentials.refresh(self._auth_request)
        return self.credentials.token
    
    async def create_project(
        self, 
        name: str, 
        description: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new project in Firestore."""
        project_id = str(uuid4())
        now = datetime.utcnow().isoformat()
        
        project_data = {
            "project_id": project_id,
            "name": name,
            "description": description,
            "user_id": user_id,
            "status": ProjectStatus.CREATED.value,
            "progress": 0,
            "files": [],
            "outputs": [],
            "error_message": None,
            "created_at": now,
            "updated_at": now
        }
        
        self.projects_collection.document(project_id).set(project_data)
        return project_data
    
    async def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Get project data from Firestore."""
        doc = self.projects_collection.document(project_id).get()
        if not doc.exists:
            return None
        return doc.to_dict()
    
    async def update_project(
        self, 
        project_id: str, 
        updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Update project data in Firestore."""
        doc_ref = self.projects_collection.document(project_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            return None
        
        updates["updated_at"] = datetime.utcnow().isoformat()
        doc_ref.update(updates)
        return doc_ref.get().to_dict()
    
    async def generate_upload_url(
        self, 
        project_id: str, 
        filename: str,
        file_size: Optional[int] = None,
        content_type: str = "application/octet-stream",
        resumable: bool = True,
        origin: Optional[str] = None
    ) -> Optional[Dict[str, str]]:
        """
        Generate URL for uploading to Cloud Storage.
        
        Args:
            project_id: Project ID
            filename: File name
            file_size: File size in bytes (required for resumable)
            content_type: MIME type
            resumable: Use resumable upload (recommended for large files)
            origin: Request origin for CORS
        
        Returns:
            Dict with upload_url, file_id and upload info
        """
        project = await self.get_project(project_id)
        if not project:
            return None
        
        file_id = str(uuid4())
        safe_filename = f"{file_id}_{filename}"
        blob_path = f"{project_id}/{safe_filename}"
        
        blob = self.uploads_bucket.blob(blob_path)
        
        if resumable and file_size:
            # Resumable upload - best for large files
            if not self.credentials.valid:
                self.credentials.refresh(self._auth_request)
            
            upload_url = blob.create_resumable_upload_session(
                content_type=content_type,
                size=file_size,
                origin=origin or "*",
                client=self.storage_client
            )
            upload_type = "resumable"
        else:
            # Simple signed URL - OK for small files (<50MB)
            upload_url = blob.generate_signed_url(
                version="v4",
                expiration=timedelta(hours=1),
                method="PUT",
                content_type=content_type,
                service_account_email=self.service_account_email,
                access_token=self._get_access_token()
            )
            upload_type = "simple"
        
        # Register pending file
        files = project.get("files", [])
        files.append({
            "file_id": file_id,
            "filename": filename,
            "safe_filename": safe_filename,
            "blob_path": blob_path,
            "size": file_size,
            "content_type": content_type,
            "status": "pending",
            "uploaded_at": None
        })
        
        await self.update_project(project_id, {
            "files": files,
            "status": ProjectStatus.UPLOADING.value
        })
        
        return {
            "upload_url": upload_url,
            "file_id": file_id,
            "blob_path": blob_path,
            "upload_type": upload_type,
            "chunk_size": 5 * 1024 * 1024 if resumable else None  # 5MB chunks
        }
    
    async def confirm_upload(self, project_id: str, file_id: str) -> bool:
        """Confirm that upload was completed by checking the blob."""
        project = await self.get_project(project_id)
        if not project:
            return False
        
        files = project.get("files", [])
        for file in files:
            if file["file_id"] == file_id:
                blob = self.uploads_bucket.blob(file["blob_path"])
                if blob.exists():
                    file["status"] = "uploaded"
                    file["uploaded_at"] = datetime.utcnow().isoformat()
                break
        
        await self.update_project(project_id, {"files": files})
        return True
    
    async def get_uploaded_files(self, project_id: str) -> List[str]:
        """List uploaded files for a project in Cloud Storage."""
        prefix = f"{project_id}/"
        blobs = self.uploads_bucket.list_blobs(prefix=prefix)
        return [blob.name.replace(prefix, "") for blob in blobs]
    
    async def list_projects(
        self, 
        user_id: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List projects from Firestore."""
        query = self.projects_collection
        
        if user_id:
            query = query.where("user_id", "==", user_id)
        
        query = query.order_by("created_at", direction=firestore.Query.DESCENDING)
        query = query.limit(limit)
        
        docs = query.stream()
        return [doc.to_dict() for doc in docs]
    
    async def generate_download_url(
        self, 
        project_id: str, 
        filename: str,
        bucket_type: str = "outputs"
    ) -> Optional[str]:
        """Generate signed URL for downloading a file."""
        bucket = self.outputs_bucket if bucket_type == "outputs" else self.uploads_bucket
        blob_path = f"{project_id}/{filename}"
        blob = bucket.blob(blob_path)
        
        if not blob.exists():
            return None
        
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(hours=1),
            method="GET",
            service_account_email=self.service_account_email,
            access_token=self._get_access_token()
        )
    
    def get_uploads_path(self, project_id: str) -> str:
        """Return GCS path for uploads."""
        return f"gs://{self.uploads_bucket_name}/{project_id}/"
    
    def get_outputs_path(self, project_id: str) -> str:
        """Return GCS path for outputs."""
        return f"gs://{self.outputs_bucket_name}/{project_id}/"
