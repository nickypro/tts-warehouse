"""Background job queue for TTS processing."""

import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Callable, Any
from queue import Queue, Empty

from src.config import get_settings
from src.database import db_session, ItemRepository, ItemStatus
from src.tts import get_tts_engine

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    """Job status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job:
    """A TTS processing job."""

    item_id: int
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


class JobQueue:
    """
    Background job queue for processing TTS jobs.
    
    Supports both eager (immediate) and lazy (on-demand) processing.
    """

    def __init__(self):
        self.settings = get_settings()
        self._queue: Queue[Job] = Queue()
        self._active_jobs: dict[int, Job] = {}
        self._completed_jobs: dict[int, Job] = {}
        self._lock = threading.Lock()
        self._processor_thread: Optional[threading.Thread] = None
        self._running = False

    def enqueue(self, item_id: int) -> Job:
        """
        Add an item to the processing queue.

        Args:
            item_id: ID of the item to process

        Returns:
            The created job
        """
        with self._lock:
            # Check if already queued or processing
            if item_id in self._active_jobs:
                return self._active_jobs[item_id]

            job = Job(item_id=item_id)
            self._active_jobs[item_id] = job
            self._queue.put(job)

        logger.info(f"Enqueued job for item {item_id}")
        return job

    def get_job_status(self, item_id: int) -> Optional[Job]:
        """Get the status of a job by item ID."""
        with self._lock:
            if item_id in self._active_jobs:
                return self._active_jobs[item_id]
            if item_id in self._completed_jobs:
                return self._completed_jobs[item_id]
        return None

    def get_queue_status(self) -> dict:
        """Get overall queue status."""
        with self._lock:
            pending = sum(1 for j in self._active_jobs.values() if j.status == JobStatus.PENDING)
            processing = sum(
                1 for j in self._active_jobs.values() if j.status == JobStatus.PROCESSING
            )
            completed = len(self._completed_jobs)
            failed = sum(
                1 for j in self._completed_jobs.values() if j.status == JobStatus.FAILED
            )

        return {
            "pending": pending,
            "processing": processing,
            "completed": completed,
            "failed": failed,
            "total_active": len(self._active_jobs),
        }

    def process_one(self, item_id: int) -> bool:
        """
        Process a single item synchronously (for lazy processing).

        Args:
            item_id: ID of the item to process

        Returns:
            True if processing succeeded, False otherwise
        """
        logger.info(f"Processing item {item_id} synchronously (lazy mode)")

        try:
            with db_session() as session:
                item = ItemRepository.get_by_id(session, item_id)
                if not item:
                    logger.error(f"Item {item_id} not found")
                    return False

                if item.status == ItemStatus.READY and item.audio_path:
                    # Already processed
                    return True

                # Mark as processing
                ItemRepository.update_status(session, item_id, ItemStatus.PROCESSING)

            # Generate audio
            success = self._process_item(item_id)

            return success

        except Exception as e:
            logger.error(f"Failed to process item {item_id}: {e}")
            with db_session() as session:
                ItemRepository.update_status(
                    session, item_id, ItemStatus.FAILED, error_message=str(e)
                )
            return False

    def _process_item(self, item_id: int) -> bool:
        """
        Process a single item (internal).

        Args:
            item_id: ID of the item to process

        Returns:
            True if processing succeeded
        """
        with db_session() as session:
            item = ItemRepository.get_by_id(session, item_id)
            if not item:
                return False

            if not item.content_text:
                ItemRepository.update_status(
                    session, item_id, ItemStatus.FAILED, error_message="No content to process"
                )
                return False

            # Extract values while in session
            content_text = item.content_text
            item_title = item.title
            source_slug = item.source.slug if item.source else f"source_{item.source_id}"

        # Generate audio path
        settings = get_settings()
        audio_dir = Path(settings.database_path).parent / "audio" / source_slug
        audio_dir.mkdir(parents=True, exist_ok=True)

        # Create safe filename
        safe_title = "".join(c if c.isalnum() or c in "-_ " else "_" for c in item_title)
        safe_title = safe_title[:100]  # Limit length
        audio_path = audio_dir / f"{item_id}_{safe_title}.mp3"

        try:
            # Get TTS engine and synthesize
            tts = get_tts_engine()
            tts.synthesize(content_text, audio_path)

            # Update item status
            with db_session() as session:
                ItemRepository.update_status(
                    session, item_id, ItemStatus.READY, audio_path=str(audio_path)
                )

            logger.info(f"Successfully processed item {item_id}: {audio_path}")
            return True

        except Exception as e:
            logger.error(f"TTS failed for item {item_id}: {e}")
            with db_session() as session:
                ItemRepository.update_status(
                    session, item_id, ItemStatus.FAILED, error_message=str(e)
                )
            return False

    def start_background_processor(self, interval_seconds: float = 2.0):
        """Start the background job processor thread."""
        if self._running:
            return

        self._running = True
        self._processor_thread = threading.Thread(
            target=self._background_processor,
            args=(interval_seconds,),
            daemon=True,
        )
        self._processor_thread.start()
        logger.info("Background job processor started")

    def stop_background_processor(self):
        """Stop the background job processor."""
        self._running = False
        if self._processor_thread:
            self._processor_thread.join(timeout=5.0)
            self._processor_thread = None
        logger.info("Background job processor stopped")

    def _background_processor(self, interval_seconds: float):
        """Background thread that processes jobs from the queue."""
        while self._running:
            try:
                # Get next job from queue (with timeout)
                try:
                    job = self._queue.get(timeout=interval_seconds)
                except Empty:
                    continue

                # Update job status
                with self._lock:
                    job.status = JobStatus.PROCESSING
                    job.started_at = datetime.utcnow()

                # Process the item
                success = self._process_item(job.item_id)

                # Update job status
                with self._lock:
                    job.completed_at = datetime.utcnow()
                    if success:
                        job.status = JobStatus.COMPLETED
                    else:
                        job.status = JobStatus.FAILED
                        job.error = "Processing failed"

                    # Move to completed
                    if job.item_id in self._active_jobs:
                        del self._active_jobs[job.item_id]
                    self._completed_jobs[job.item_id] = job

            except Exception as e:
                logger.error(f"Error in background processor: {e}")


# Singleton instance
_job_queue: Optional[JobQueue] = None


def get_job_queue() -> JobQueue:
    """Get the job queue singleton instance."""
    global _job_queue
    if _job_queue is None:
        _job_queue = JobQueue()
    return _job_queue
