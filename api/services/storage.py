"""
Storage Service - Google Cloud Platform

Handles all storage operations:
- Cloud Storage: Image uploads and processed outputs
- Firestore: Project metadata and status tracking
"""
import asyncio
import logging
import os
import re
import threading
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any
from uuid import uuid4

import google.auth
from google.auth.transport import requests
from google.cloud import firestore, storage

from models import ProjectStatus

logger = logging.getLogger(__name__)


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename to prevent path traversal and injection attacks.

    - Removes path components (../, .\\, absolute paths)
    - Keeps only the basename
    - Removes null bytes and control characters
    - Restricts to safe characters (alphanumeric, dash, underscore, dot)
    - Limits length to 255 characters
    """
    # Remove null bytes
    filename = filename.replace("\x00", "")

    # Extract only the basename (removes any path components like ../ or C:\)
    # Try Windows-style first (handles C:\path), then POSIX (handles /path)
    filename = PureWindowsPath(filename).name
    filename = PurePosixPath(filename).name

    # Remove any remaining path traversal patterns
    filename = filename.replace("..", "")

    # Keep only safe characters: letters, numbers, dash, underscore, dot, space
    filename = re.sub(r'[^A-Za-z0-9_.\- ]', '_', filename)

    # Remove leading/trailing dots and spaces (prevents hidden files)
    filename = filename.strip('. ')

    # Limit length
    if len(filename) > 255:
        p = PurePosixPath(filename)
        ext = p.suffix
        name = p.stem
        filename = name[:255 - len(ext)] + ext

    # Fallback if empty after sanitization
    if not filename:
        filename = "unnamed_file"

    return filename


class StorageService:
    """
    Storage service using GCP.
    - Cloud Storage: uploads and outputs
    - Firestore: project metadata

    All public async methods offload blocking GCP SDK calls to a thread pool
    via ``asyncio.to_thread`` so the event loop is never blocked.
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
        self._credentials_lock = threading.Lock()

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
            metadata_url = (
                "http://metadata.google.internal/computeMetadata/v1/"
                "instance/service-accounts/default/email"
            )
            req = urllib.request.Request(metadata_url, headers={"Metadata-Flavor": "Google"})
            with urllib.request.urlopen(req, timeout=2) as response:
                return response.read().decode('utf-8')
        except Exception:
            pass

        # 4. Fallback
        return f"photogrammetry-api@{self.project_id}.iam.gserviceaccount.com"

    def _get_access_token(self) -> str:
        """Get updated access token for signing URLs."""
        with self._credentials_lock:
            if not self.credentials.valid:
                self.credentials.refresh(self._auth_request)
        return self.credentials.token

    # ------------------------------------------------------------------
    # Firestore helpers (sync, called via asyncio.to_thread)
    # ------------------------------------------------------------------

    def _create_project_sync(
        self, name: str, description: str | None, user_id: str | None
    ) -> dict[str, Any]:
        project_id = str(uuid4())
        now = datetime.now(UTC).isoformat()

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
            "updated_at": now,
        }

        self.projects_collection.document(project_id).set(project_data, timeout=10)
        return project_data

    def _get_project_sync(self, project_id: str) -> dict[str, Any] | None:
        doc = self.projects_collection.document(project_id).get(timeout=10)
        if not doc.exists:
            return None
        return doc.to_dict()

    def _update_project_sync(
        self, project_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        doc_ref = self.projects_collection.document(project_id)
        doc = doc_ref.get(timeout=10)

        if not doc.exists:
            return None

        updates["updated_at"] = datetime.now(UTC).isoformat()
        doc_ref.update(updates, timeout=10)
        return doc_ref.get(timeout=10).to_dict()

    def _list_projects_sync(
        self, user_id: str | None, limit: int
    ) -> list[dict[str, Any]]:
        query = self.projects_collection

        if user_id:
            query = query.where("user_id", "==", user_id)

        query = query.order_by("created_at", direction=firestore.Query.DESCENDING)
        query = query.limit(limit)

        docs = query.stream(timeout=10)
        return [doc.to_dict() for doc in docs]

    def _get_uploaded_files_sync(self, project_id: str) -> list[str]:
        prefix = f"{project_id}/"
        blobs = self.uploads_bucket.list_blobs(prefix=prefix, max_results=5000)
        return [blob.name.replace(prefix, "") for blob in blobs]

    # ------------------------------------------------------------------
    # Transactional helpers (prevent race conditions on shared state)
    # ------------------------------------------------------------------

    def _append_file_sync(
        self, project_id: str, file_data: dict[str, Any]
    ) -> bool:
        """Atomically append a file entry to the project's files list."""
        doc_ref = self.projects_collection.document(project_id)
        transaction = self.firestore_client.transaction()

        @firestore.transactional
        def _txn(transaction):
            doc = doc_ref.get(transaction=transaction)
            if not doc.exists:
                return False
            project_data = doc.to_dict()
            files = project_data.get("files", [])
            files.append(file_data)
            transaction.update(doc_ref, {
                "files": files,
                "status": ProjectStatus.UPLOADING.value,
                "updated_at": datetime.now(UTC).isoformat(),
            })
            return True

        return _txn(transaction)

    def _confirm_file_sync(self, project_id: str, file_id: str) -> bool:
        """Atomically mark a file as uploaded in the project's files list."""
        doc_ref = self.projects_collection.document(project_id)
        transaction = self.firestore_client.transaction()

        @firestore.transactional
        def _txn(transaction):
            doc = doc_ref.get(transaction=transaction)
            if not doc.exists:
                return False
            project_data = doc.to_dict()
            files = project_data.get("files", [])
            found = False
            for f in files:
                if f["file_id"] == file_id:
                    f["status"] = "uploaded"
                    f["uploaded_at"] = datetime.now(UTC).isoformat()
                    found = True
                    break
            if found:
                transaction.update(doc_ref, {
                    "files": files,
                    "updated_at": datetime.now(UTC).isoformat(),
                })
            return found

        return _txn(transaction)

    def _transition_status_sync(
        self,
        project_id: str,
        allowed_from: list[str],
        new_status: str,
        extra_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """
        Atomically transition project status.

        Returns:
            Updated project dict on success.
            None if project not found.
            Dict with ``__rejected`` key if current status is not in *allowed_from*.
        """
        doc_ref = self.projects_collection.document(project_id)
        transaction = self.firestore_client.transaction()

        @firestore.transactional
        def _txn(transaction):
            doc = doc_ref.get(transaction=transaction)
            if not doc.exists:
                return None
            data = doc.to_dict()
            current = data.get("status")
            if current not in allowed_from:
                return {"__rejected": True, "current_status": current}
            updates = {
                "status": new_status,
                "updated_at": datetime.now(UTC).isoformat(),
            }
            if extra_updates:
                updates.update(extra_updates)
            transaction.update(doc_ref, updates)
            return {**data, **updates}

        return _txn(transaction)

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def create_project(
        self,
        name: str,
        description: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new project in Firestore."""
        return await asyncio.to_thread(self._create_project_sync, name, description, user_id)

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        """Get project data from Firestore."""
        return await asyncio.to_thread(self._get_project_sync, project_id)

    async def update_project(
        self,
        project_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Update project data in Firestore."""
        return await asyncio.to_thread(self._update_project_sync, project_id, updates)

    async def get_uploaded_files(self, project_id: str) -> list[str]:
        """List uploaded files for a project in Cloud Storage."""
        return await asyncio.to_thread(self._get_uploaded_files_sync, project_id)

    async def list_projects(
        self,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List projects from Firestore."""
        return await asyncio.to_thread(self._list_projects_sync, user_id, limit)

    async def transition_status(
        self,
        project_id: str,
        allowed_from: list[str],
        new_status: str,
        extra_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Atomically transition project status if current status is in *allowed_from*."""
        return await asyncio.to_thread(
            self._transition_status_sync,
            project_id,
            allowed_from,
            new_status,
            extra_updates,
        )

    async def generate_upload_url(
        self,
        project_id: str,
        filename: str,
        file_size: int | None = None,
        content_type: str = "application/octet-stream",
        resumable: bool = True,
        origin: str | None = None,
    ) -> dict[str, str] | None:
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
        clean_filename = sanitize_filename(filename)
        safe_filename = f"{file_id}_{clean_filename}"
        blob_path = f"{project_id}/{safe_filename}"

        blob = self.uploads_bucket.blob(blob_path)

        if resumable and file_size:
            # Resumable upload — offload blocking call
            def _create_session():
                self._get_access_token()
                return blob.create_resumable_upload_session(
                    content_type=content_type,
                    size=file_size,
                    origin=origin,
                    client=self.storage_client,
                )

            upload_url = await asyncio.to_thread(_create_session)
            upload_type = "resumable"
        else:
            # Simple signed URL — offload blocking call
            def _sign_url():
                return blob.generate_signed_url(
                    version="v4",
                    expiration=timedelta(minutes=15),
                    method="PUT",
                    content_type=content_type,
                    service_account_email=self.service_account_email,
                    access_token=self._get_access_token(),
                )

            upload_url = await asyncio.to_thread(_sign_url)
            upload_type = "simple"

        # Register pending file atomically (prevents concurrent append races)
        file_data = {
            "file_id": file_id,
            "filename": clean_filename,
            "safe_filename": safe_filename,
            "blob_path": blob_path,
            "size": file_size,
            "content_type": content_type,
            "status": "pending",
            "uploaded_at": None,
        }
        await asyncio.to_thread(self._append_file_sync, project_id, file_data)

        return {
            "upload_url": upload_url,
            "file_id": file_id,
            "blob_path": blob_path,
            "upload_type": upload_type,
            "chunk_size": 5 * 1024 * 1024 if resumable else None,  # 5MB chunks
        }

    async def confirm_upload(self, project_id: str, file_id: str) -> bool:
        """Confirm that upload was completed by checking the blob in GCS,
        then atomically update the file status in Firestore."""
        project = await self.get_project(project_id)
        if not project:
            return False

        # Find the file's blob_path
        blob_path = None
        for f in project.get("files", []):
            if f["file_id"] == file_id:
                blob_path = f.get("blob_path")
                break

        if not blob_path:
            return False

        # Verify blob exists in Cloud Storage
        blob = self.uploads_bucket.blob(blob_path)
        exists = await asyncio.to_thread(blob.exists)
        if not exists:
            return False

        # Atomically update file status in Firestore
        await asyncio.to_thread(self._confirm_file_sync, project_id, file_id)
        return True

    async def generate_download_url(
        self,
        project_id: str,
        filename: str,
        bucket_type: str = "outputs",
    ) -> str | None:
        """Generate signed URL for downloading a file."""
        bucket = self.outputs_bucket if bucket_type == "outputs" else self.uploads_bucket
        # Sanitize filename to prevent path traversal (e.g. "../other-project/secret")
        safe_name = sanitize_filename(filename)
        blob_path = f"{project_id}/{safe_name}"
        blob = bucket.blob(blob_path)

        exists = await asyncio.to_thread(blob.exists)
        if not exists:
            return None

        def _sign():
            return blob.generate_signed_url(
                version="v4",
                expiration=timedelta(minutes=15),
                method="GET",
                service_account_email=self.service_account_email,
                access_token=self._get_access_token(),
            )

        return await asyncio.to_thread(_sign)

    def get_uploads_path(self, project_id: str) -> str:
        """Return GCS path for uploads."""
        return f"gs://{self.uploads_bucket_name}/{project_id}/"

    def get_outputs_path(self, project_id: str) -> str:
        """Return GCS path for outputs."""
        return f"gs://{self.outputs_bucket_name}/{project_id}/"
