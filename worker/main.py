"""
Photogrammetry Worker for Google Cloud Batch.

This worker handles the complete photogrammetry processing pipeline:
1. Downloads images from Cloud Storage
2. Executes OpenDroneMap processing
3. Uploads results to Cloud Storage
4. Updates project status in Firestore
"""
import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from google.cloud import firestore, pubsub_v1, storage

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


@dataclass
class WorkerConfig:
    """Worker configuration from environment variables."""
    gcp_project: str = field(default_factory=lambda: os.environ.get("GCP_PROJECT", ""))
    uploads_bucket: str = field(default_factory=lambda: os.environ.get("UPLOADS_BUCKET", ""))
    outputs_bucket: str = field(default_factory=lambda: os.environ.get("OUTPUTS_BUCKET", ""))

    # ODM processing options
    ortho_quality: str = field(default_factory=lambda: os.environ.get("ORTHO_QUALITY", "medium"))
    generate_dtm: bool = field(default_factory=lambda: os.environ.get("GENERATE_DTM", "false").lower() == "true")
    multispectral: bool = field(default_factory=lambda: os.environ.get("MULTISPECTRAL", "false").lower() == "true")

    def __post_init__(self):
        if not self.gcp_project:
            raise ValueError("GCP_PROJECT environment variable is required")
        if not self.uploads_bucket:
            self.uploads_bucket = f"{self.gcp_project}-photogrammetry-uploads"
        if not self.outputs_bucket:
            self.outputs_bucket = f"{self.gcp_project}-photogrammetry-outputs"


@dataclass
class ODMSettings:
    """OpenDroneMap processing settings based on quality level."""
    pc_quality: str
    feature_quality: str
    fast_orthophoto: bool

    @classmethod
    def from_quality(cls, quality: str) -> "ODMSettings":
        """Create settings from quality level (low, medium, high)."""
        presets = {
            "low": cls(pc_quality="low", feature_quality="low", fast_orthophoto=True),
            "medium": cls(pc_quality="medium", feature_quality="medium", fast_orthophoto=False),
            "high": cls(pc_quality="high", feature_quality="high", fast_orthophoto=False),
        }
        return presets.get(quality, presets["medium"])


class PhotogrammetryWorker:
    """
    Worker that processes photogrammetry projects using OpenDroneMap.

    Handles the complete pipeline from downloading images to uploading results.
    """

    # Directory structure expected by ODM
    WORK_DIR = Path("/work")
    PROJECT_NAME = "project"

    # Supported image formats
    SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

    # Output files to upload (source_path, dest_name, output_type)
    OUTPUT_FILES = [
        ("odm_orthophoto/odm_orthophoto.tif", "orthophoto.tif", "orthophoto"),
        ("odm_dem/dsm.tif", "dsm.tif", "dsm"),
        ("odm_dem/dtm.tif", "dtm.tif", "dtm"),
        ("odm_georeferencing/odm_georeferenced_model.laz", "pointcloud.laz", "pointcloud"),
    ]

    # Progress estimation patterns (pattern, progress_percentage)
    PROGRESS_PATTERNS = [
        ("loading dataset", 5),
        ("found images", 8),
        ("running opensfm", 10),
        ("extracting", 12),
        ("detecting features", 15),
        ("matching", 20),
        ("creating tracks", 25),
        ("reconstructing", 30),
        ("undistort", 35),
        ("openmvs", 40),
        ("densif", 45),
        ("filterpoints", 50),
        ("meshing", 55),
        ("texturing", 60),
        ("georeferenc", 70),
        ("transform", 75),
        ("dem", 80),
        ("orthophoto", 85),
        ("cutting", 88),
        ("finished", 95),
        ("completed", 95),
    ]

    def __init__(self, config: WorkerConfig):
        self.config = config
        self.project_dir = self.WORK_DIR / self.PROJECT_NAME
        self.images_dir = self.project_dir / "images"

        # Initialize GCP clients
        self.storage_client = storage.Client(project=config.gcp_project)
        self.firestore_client = firestore.Client(project=config.gcp_project)

        self.uploads_bucket = self.storage_client.bucket(config.uploads_bucket)
        self.outputs_bucket = self.storage_client.bucket(config.outputs_bucket)
        self.projects_collection = self.firestore_client.collection("projects")

        # Pub/Sub publisher - use existing photogrammetry-status topic
        self.pubsub_publisher = pubsub_v1.PublisherClient()
        self.pubsub_topic_name = os.environ.get("PUBSUB_TOPIC", "photogrammetry-status")
        self.pubsub_topic_path = self.pubsub_publisher.topic_path(config.gcp_project, self.pubsub_topic_name)

        logger.info("Worker initialized")
        logger.info(f"  GCP Project: {config.gcp_project}")
        logger.info(f"  Uploads bucket: {config.uploads_bucket}")
        logger.info(f"  Outputs bucket: {config.outputs_bucket}")

    def publish_event(self, event_type: str, project_id: str, data: dict[str, Any]) -> None:
        """Publish event to Pub/Sub."""
        try:
            message_data = {
                "event_type": event_type,
                "project_id": project_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "data": data
            }
            message_bytes = json.dumps(message_data).encode("utf-8")
            future = self.pubsub_publisher.publish(self.pubsub_topic_path, message_bytes)
            future.result()  # Wait for publish
            logger.info(f"Published event: {event_type} for project {project_id}")
        except Exception as e:
            logger.warning(f"Failed to publish Pub/Sub event: {e}")

    def update_status(
        self,
        project_id: str,
        status: str,
        progress: int | None = None,
        error: str | None = None,
        outputs: list[dict] | None = None
    ) -> None:
        """Update project status in Firestore."""
        try:
            updates: dict[str, Any] = {
                "status": status,
                "updated_at": datetime.now(UTC).isoformat()
            }

            if progress is not None:
                updates["progress"] = progress
            if error:
                updates["error_message"] = error
            if outputs:
                updates["outputs"] = outputs

            doc_ref = self.projects_collection.document(project_id)
            doc_ref.update(updates)
            logger.info(f"Status updated: {status}" + (f" ({progress}%)" if progress else ""))
        except Exception as e:
            logger.error(f"Failed to update Firestore status for {project_id}: {e}")
            # Don't raise - continue processing even if status update fails

    def download_images(self, project_id: str) -> list[Path]:
        """Download images from Cloud Storage."""
        self.images_dir.mkdir(parents=True, exist_ok=True)

        prefix = f"{project_id}/"
        blobs = list(self.uploads_bucket.list_blobs(prefix=prefix))
        logger.info(f"Found {len(blobs)} files in storage")

        downloaded: list[Path] = []
        for i, blob in enumerate(blobs):
            filename = blob.name.replace(prefix, "")
            extension = Path(filename).suffix.lower()

            if extension not in self.SUPPORTED_EXTENSIONS:
                continue

            local_path = self.images_dir / filename
            blob.download_to_filename(str(local_path))
            downloaded.append(local_path)

            if (i + 1) % 100 == 0:
                logger.info(f"Downloaded {i + 1}/{len(blobs)} files")

        logger.info(f"Download complete: {len(downloaded)} images")
        return downloaded

    def build_odm_command(self) -> list[str]:
        """Build ODM command with appropriate settings."""
        settings = ODMSettings.from_quality(self.config.ortho_quality)

        cmd = [
            "python3", "/code/run.py",
            "--project-path", str(self.WORK_DIR),
            "--max-concurrency", str(os.cpu_count() or 4),
            "--pc-quality", settings.pc_quality,
            "--feature-quality", settings.feature_quality,
        ]

        if settings.fast_orthophoto:
            cmd.extend(["--fast-orthophoto", "--skip-3dmodel"])
        else:
            cmd.append("--dsm")
            if self.config.generate_dtm:
                cmd.append("--dtm")

        # Skip report generation due to GDAL compatibility issue in ODM Docker image
        # See: https://github.com/OpenDroneMap/ODM/issues/1234
        cmd.append("--skip-report")

        if self.config.multispectral:
            cmd.extend(["--radiometric-calibration", "camera", "--rolling-shutter"])

        # Project name must be last positional argument
        cmd.append(self.PROJECT_NAME)

        return cmd

    def estimate_progress(self, log_line: str) -> int:
        """Estimate processing progress from ODM log output."""
        line_lower = log_line.lower()
        for pattern, progress in self.PROGRESS_PATTERNS:
            if pattern in line_lower:
                return progress
        return 0

    def run_odm(self, project_id: str) -> None:
        """Execute OpenDroneMap processing."""
        cmd = self.build_odm_command()
        logger.info(f"ODM settings: quality={self.config.ortho_quality}, dtm={self.config.generate_dtm}, multispectral={self.config.multispectral}")
        logger.info(f"Executing ODM: {' '.join(cmd[:5])}...")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(self.WORK_DIR)
        )

        last_progress = 0
        for line in process.stdout:
            line = line.strip()
            if line:
                logger.info(f"[ODM] {line}")

                new_progress = self.estimate_progress(line)
                if new_progress > last_progress:
                    last_progress = new_progress
                    self.update_status(project_id, "processing", progress=new_progress)

        process.wait()

        if process.returncode != 0:
            raise RuntimeError(f"ODM failed with exit code {process.returncode}")

    def upload_results(self, project_id: str) -> list[dict[str, Any]]:
        """Upload processing results to Cloud Storage."""
        outputs: list[dict[str, Any]] = []

        for src_path, dest_name, output_type in self.OUTPUT_FILES:
            local_path = self.project_dir / src_path

            if not local_path.exists():
                logger.warning(f"Output file not found: {src_path}")
                continue

            blob_path = f"{project_id}/{dest_name}"
            blob = self.outputs_bucket.blob(blob_path)

            logger.info(f"Uploading {dest_name}...")
            blob.upload_from_filename(str(local_path))

            size_bytes = local_path.stat().st_size
            size_mb = round(size_bytes / (1024 * 1024), 2)

            outputs.append({
                "type": output_type,
                "filename": dest_name,
                "size_mb": size_mb,
                "gcs_path": f"gs://{self.config.outputs_bucket}/{blob_path}",
                "created_at": datetime.now(UTC).isoformat()
            })

            logger.info(f"Uploaded {dest_name} ({size_mb} MB)")

        return outputs

    def cleanup(self) -> None:
        """Clean up temporary files."""
        try:
            if self.project_dir.exists():
                shutil.rmtree(self.project_dir)
                logger.info("Temporary files cleaned up")
        except Exception as e:
            logger.warning(f"Failed to clean up temporary files: {e}")

    def process(self, project_id: str) -> bool:
        """
        Process a complete photogrammetry project.

        Args:
            project_id: The project ID to process

        Returns:
            True if processing completed successfully, False otherwise
        """
        logger.info("=" * 60)
        logger.info(f"Starting processing: {project_id}")
        logger.info("=" * 60)

        try:
            self.update_status(project_id, "processing", progress=0)

            # Step 1: Download images
            logger.info("Step 1/4: Downloading images...")
            images = self.download_images(project_id)

            if not images:
                raise ValueError("No images found in storage")

            self.update_status(project_id, "processing", progress=10)
            logger.info(f"Downloaded {len(images)} images")

            # Step 2: Run ODM
            logger.info("Step 2/4: Running OpenDroneMap...")
            self.run_odm(project_id)
            self.update_status(project_id, "processing", progress=90)

            # Step 3: Upload results
            logger.info("Step 3/4: Uploading results...")
            outputs = self.upload_results(project_id)
            self.update_status(project_id, "processing", progress=95)

            # Step 4: Finalize
            logger.info("Step 4/4: Finalizing...")
            self.update_status(project_id, "completed", progress=100, outputs=outputs)

            # Publish completion event
            self.publish_event("project.completed", project_id, {
                "outputs_count": len(outputs),
                "outputs": [
                    {
                        "type": o.get("type"),
                        "filename": o.get("filename"),
                        "size_mb": o.get("size_mb")
                    }
                    for o in outputs
                ]
            })

            logger.info("=" * 60)
            logger.info("Processing completed successfully")
            logger.info(f"Outputs: {len(outputs)} files")
            logger.info("=" * 60)

            return True

        except Exception as e:
            logger.error(f"Processing failed: {e}")
            self.update_status(project_id, "failed", error=str(e))

            # Publish failure event
            self.publish_event("project.failed", project_id, {"error": str(e)})

            return False

        finally:
            self.cleanup()


def main() -> None:
    """Worker entry point."""
    project_id = os.environ.get("PROJECT_ID")

    if not project_id and len(sys.argv) > 1:
        project_id = sys.argv[1]

    if not project_id:
        logger.error("PROJECT_ID not defined")
        logger.error("Usage: python main.py <project_id>")
        logger.error("Or set the PROJECT_ID environment variable")
        sys.exit(1)

    try:
        config = WorkerConfig()
        worker = PhotogrammetryWorker(config)
        success = worker.process(project_id)
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"Worker initialization failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
