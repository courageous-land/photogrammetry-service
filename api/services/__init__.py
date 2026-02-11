"""
Photogrammetry Service - Services Layer

This module initializes all services required for the photogrammetry processing API.
Services handle communication with GCP resources (Cloud Storage, Firestore, Cloud Batch).
"""
from services.batch import BatchService
from services.processor import ProcessorService
from services.pubsub import PubSubService
from services.storage import StorageService

# Initialize services
storage_service = StorageService()
batch_service = BatchService()
pubsub_service = PubSubService()
processor_service = ProcessorService(
    storage_service=storage_service,
    batch_service=batch_service
)

__all__ = [
    "storage_service",
    "batch_service",
    "pubsub_service",
    "processor_service",
    "StorageService",
    "BatchService",
    "PubSubService",
    "ProcessorService",
]
