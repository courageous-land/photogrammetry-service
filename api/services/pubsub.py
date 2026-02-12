"""
Pub/Sub Service

Handles publishing events for photogrammetry processing lifecycle.
"""
import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from google.cloud import pubsub_v1

logger = logging.getLogger(__name__)


class PubSubService:
    """
    Service for publishing events to Pub/Sub.

    The underlying ``PublisherClient.publish()`` is blocking (waits for
    server ack via ``future.result()``), so all calls are offloaded to
    a thread pool via ``asyncio.to_thread``.
    """

    def __init__(self):
        self.project_id = os.environ.get("GCP_PROJECT")
        if not self.project_id:
            raise ValueError("GCP_PROJECT environment variable is required")

        # Use existing topics: photogrammetry-status for status updates
        self.topic_name = os.environ.get(
            "PUBSUB_TOPIC",
            "photogrammetry-status"
        )

        self.publisher = pubsub_v1.PublisherClient()
        self.topic_path = self.publisher.topic_path(self.project_id, self.topic_name)

    def _publish_sync(self, message_bytes: bytes) -> str:
        """Synchronous publish — called via asyncio.to_thread."""
        future = self.publisher.publish(self.topic_path, message_bytes)
        return future.result(timeout=30)

    async def publish_event(
        self,
        event_type: str,
        project_id: str,
        data: dict[str, Any],
    ) -> str:
        """
        Publish an event to Pub/Sub.

        Args:
            event_type: Type of event (e.g., 'project.created', 'project.completed')
            project_id: Project ID
            data: Additional event data

        Returns:
            Message ID (empty string on failure)
        """
        message_data = {
            "event_type": event_type,
            "project_id": project_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "data": data,
        }

        message_bytes = json.dumps(message_data).encode("utf-8")

        try:
            message_id = await asyncio.to_thread(self._publish_sync, message_bytes)
            return message_id
        except Exception as e:
            # Log error but don't fail the request
            logger.error("Failed to publish Pub/Sub event: %s", e)
            return ""

    async def publish_project_created(self, project_id: str, project_data: dict[str, Any]):
        """Publish project created event."""
        return await self.publish_event(
            "project.created",
            project_id,
            {"name": project_data.get("name"), "status": project_data.get("status")},
        )

    async def publish_project_processing_started(
        self, project_id: str, job_info: dict[str, Any]
    ):
        """Publish processing started event."""
        return await self.publish_event(
            "project.processing_started",
            project_id,
            {
                "job_id": job_info.get("job_id"),
                "machine_type": job_info.get("machine_type"),
                "file_count": job_info.get("file_count"),
            },
        )

    async def publish_project_completed(self, project_id: str, outputs: list):
        """Publish project completed event."""
        return await self.publish_event(
            "project.completed",
            project_id,
            {
                "outputs_count": len(outputs),
                "outputs": [
                    {
                        "type": o.get("type"),
                        "filename": o.get("filename"),
                        "size_mb": o.get("size_mb"),
                    }
                    for o in outputs
                ],
            },
        )

    async def publish_project_failed(self, project_id: str, error_message: str):
        """Publish project failed event."""
        return await self.publish_event(
            "project.failed",
            project_id,
            {"error": error_message},
        )
