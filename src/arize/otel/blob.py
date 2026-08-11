import atexit
import base64
import hashlib
import heapq
import logging
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional, Protocol

from .blob_client import (
    ArizeBlobClient,
    BlobDestination,
    BlobGrant,
    BlobHTTPError,
    BlobMetadata,
    BlobStatus,
    BlobTransportError,
    BlobUploadResult,
    ExistingBlobReference,
)
from .otel import Endpoint, _get_routing_context
from .settings import (
    get_env_arize_api_key,
    get_env_arize_space_id,
    get_env_collector_endpoint,
    get_env_blob_endpoint,
    get_env_project_name,
)

logger = logging.getLogger(__name__)

_RFC3339_EXCESS_FRACTION = re.compile(r"(\.\d{6})\d+(?=(?:Z|[+-]\d{2}:\d{2})$)")

_DEFAULT_QUEUE_MAX_BYTES = 64 * 1024 * 1024
_DEFAULT_QUEUE_MAX_ITEMS = 128
_DEFAULT_STATUS_MAX_ITEMS = 1024
_DEFAULT_UPLOAD_WORKERS = 2
_DEFAULT_STATUS_POLL_INTERVAL_SECONDS = 30.0
_DEFAULT_STATUS_TIMEOUT_SECONDS = 10 * 60.0
_DEFAULT_MAX_UPLOAD_ATTEMPTS = 2


class Blob(Protocol):
    data: bytes
    mime_type: str


class _BlobClient(Protocol):
    def request_upload(
        self,
        metadata: BlobMetadata,
        destination: BlobDestination,
    ) -> BlobUploadResult: ...

    def upload_bytes(self, grant: BlobGrant, data: bytes) -> None: ...

    def get_status(
        self,
        reference: str,
        destination: BlobDestination,
    ) -> BlobStatus: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class _UploadJob:
    grant: BlobGrant
    metadata: BlobMetadata
    data: bytes = field(repr=False)
    destination: BlobDestination
    attempt: int = 1


@dataclass(order=True, frozen=True)
class _StatusJob:
    run_at: float
    sequence: int
    reference: str = field(compare=False)
    destination: BlobDestination = field(compare=False)
    deadline: float = field(compare=False)


class _ByteBudget:
    def __init__(self, maximum: int) -> None:
        if maximum <= 0:
            raise ValueError("queue_max_bytes must be positive")
        self._maximum = maximum
        self._used = 0
        self._lock = threading.Lock()

    def reserve(self, size: int) -> bool:
        with self._lock:
            if size > self._maximum - self._used:
                return False
            self._used += size
            return True

    def release(self, size: int) -> None:
        with self._lock:
            self._used -= size


class ArizeBlobUploader:
    """OpenInference BlobUploader backed by Arize blob upload grants."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        space_id: Optional[str] = None,
        project_name: Optional[str] = None,
        endpoint: Optional[str] = None,
        request_timeout_seconds: float = 1.0,
        upload_timeout_seconds: float = 30.0,
        upload_workers: int = _DEFAULT_UPLOAD_WORKERS,
        queue_max_items: int = _DEFAULT_QUEUE_MAX_ITEMS,
        queue_max_bytes: int = _DEFAULT_QUEUE_MAX_BYTES,
        status_max_items: int = _DEFAULT_STATUS_MAX_ITEMS,
        status_poll_interval_seconds: float = _DEFAULT_STATUS_POLL_INTERVAL_SECONDS,
        status_timeout_seconds: float = _DEFAULT_STATUS_TIMEOUT_SECONDS,
        max_upload_attempts: int = _DEFAULT_MAX_UPLOAD_ATTEMPTS,
        verify: Any = True,
        upload_verify: Any = True,
        client: Optional[_BlobClient] = None,
    ) -> None:
        resolved_api_key = api_key or get_env_arize_api_key()
        resolved_space_id = space_id or get_env_arize_space_id()
        resolved_project_name = project_name or get_env_project_name()
        resolved_endpoint = (
            endpoint
            or get_env_blob_endpoint()
            or get_env_collector_endpoint()
            or Endpoint.ARIZE.value
        )

        if not resolved_api_key and client is None:
            raise ValueError("api_key is required; pass it or set ARIZE_API_KEY")
        if upload_workers <= 0:
            raise ValueError("upload_workers must be positive")
        if queue_max_items <= 0:
            raise ValueError("queue_max_items must be positive")
        if status_max_items <= 0:
            raise ValueError("status_max_items must be positive")
        if status_poll_interval_seconds < 0:
            raise ValueError("status_poll_interval_seconds must be non-negative")
        if status_timeout_seconds <= 0:
            raise ValueError("status_timeout_seconds must be positive")
        if max_upload_attempts <= 0:
            raise ValueError("max_upload_attempts must be positive")

        self._destination = BlobDestination(
            space_id=resolved_space_id,
            project_name=resolved_project_name,
        )
        self._client = client or ArizeBlobClient(
            api_key=resolved_api_key,
            endpoint=resolved_endpoint,
            request_timeout_seconds=request_timeout_seconds,
            upload_timeout_seconds=upload_timeout_seconds,
            verify=verify,
            upload_verify=upload_verify,
        )
        self._upload_workers_count = upload_workers
        self._queue_max_items = queue_max_items
        self._upload_queue = queue.Queue(maxsize=queue_max_items)
        self._byte_budget = _ByteBudget(queue_max_bytes)
        self._status_max_items = status_max_items
        self._status_poll_interval = status_poll_interval_seconds
        self._status_timeout = status_timeout_seconds
        self._max_upload_attempts = max_upload_attempts

        self._lifecycle_lock = threading.Lock()
        self._pending_condition = threading.Condition()
        self._pending_uploads = 0
        self._accepting = True
        self._closed = False
        self._workers_started = False
        self._upload_stopping = threading.Event()
        self._upload_threads: List[threading.Thread] = []

        self._status_condition = threading.Condition()
        self._status_jobs: List[_StatusJob] = []
        self._status_sequence = 0
        self._status_stopping = False
        self._status_thread: Optional[threading.Thread] = None
        self._missing_destination_warned = False

        atexit.register(self.shutdown)

    def upload(self, blob: Blob) -> Optional[str]:
        data = blob.data
        if not isinstance(data, bytes) or not data:
            return None
        if not isinstance(blob.mime_type, str) or not blob.mime_type:
            return None

        destination = self._current_destination()
        if not destination.space_id or not destination.project_name:
            self._warn_missing_destination_once()
            return None

        with self._lifecycle_lock:
            if not self._accepting:
                return None
            if not self._byte_budget.reserve(len(data)):
                logger.warning(
                    "Arize blob upload queue is full; oversized content will be redacted"
                )
                return None
            with self._pending_condition:
                if self._pending_uploads >= self._queue_max_items:
                    self._byte_budget.release(len(data))
                    logger.warning(
                        "Arize blob upload queue is full; oversized content will be redacted"
                    )
                    return None
                self._pending_uploads += 1

        try:
            metadata = BlobMetadata(
                mime_type=blob.mime_type,
                size_bytes=len(data),
                md5_base64=_md5_base64(data),
            )
        except Exception as error:
            logger.warning(
                "Arize blob checksum calculation failed (%s); oversized content will be redacted",
                type(error).__name__,
            )
            self._complete_upload(len(data))
            return None
        try:
            result = self._client.request_upload(metadata, destination)
        except Exception as error:
            logger.warning(
                "Arize blob grant request failed (%s); oversized content will be redacted",
                type(error).__name__,
            )
            self._complete_upload(len(data))
            return None

        if isinstance(result, ExistingBlobReference):
            self._complete_upload(len(data))
            return result.reference

        job = _UploadJob(
            grant=result,
            metadata=metadata,
            data=data,
            destination=destination,
        )
        with self._lifecycle_lock:
            if not self._accepting:
                self._complete_upload(len(data))
                return None
            try:
                self._ensure_workers_started_locked()
            except RuntimeError as error:
                logger.warning(
                    "Arize blob upload workers could not start (%s); oversized content will be redacted",
                    type(error).__name__,
                )
                self._complete_upload(len(data))
                return None
            try:
                self._upload_queue.put_nowait(job)
            except queue.Full:
                self._complete_upload(len(data))
                logger.warning(
                    "Arize blob upload queue is full; oversized content will be redacted"
                )
                return None
        return result.reference

    def shutdown(self, timeout_sec: float = 10.0) -> None:
        timeout_sec = max(timeout_sec, 0.0)
        with self._lifecycle_lock:
            if self._closed:
                return
            self._accepting = False

        deadline = time.monotonic() + timeout_sec
        with self._pending_condition:
            while self._pending_uploads:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._pending_condition.wait(timeout=remaining)

        with self._status_condition:
            self._status_stopping = True
            self._status_jobs.clear()
            self._status_condition.notify_all()

        self._upload_stopping.set()
        self._cancel_queued_uploads()
        for thread in self._upload_threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(timeout=remaining)
        if self._status_thread is not None:
            remaining = deadline - time.monotonic()
            if remaining > 0:
                self._status_thread.join(timeout=remaining)
        self._client.close()
        with self._lifecycle_lock:
            self._closed = True

    def _current_destination(self) -> BlobDestination:
        space_id, project_name = _get_routing_context()
        if space_id and project_name:
            return BlobDestination(
                space_id=space_id,
                project_name=project_name,
            )
        return self._destination

    def _ensure_workers_started_locked(self) -> None:
        if self._workers_started:
            return
        for index in range(self._upload_workers_count):
            thread = threading.Thread(
                target=self._upload_worker,
                name=f"arize-blob-upload-{index}",
                daemon=True,
            )
            try:
                thread.start()
            except RuntimeError:
                if not self._upload_threads:
                    raise
                logger.warning("Arize blob uploader started a reduced worker pool")
                break
            self._upload_threads.append(thread)
        self._workers_started = True

        self._status_thread = threading.Thread(
            target=self._status_worker,
            name="arize-blob-status",
            daemon=True,
        )
        try:
            self._status_thread.start()
        except RuntimeError:
            self._status_thread = None
            self._status_stopping = True
            logger.warning(
                "Arize blob status worker could not start; uploads will not be monitored"
            )

    def _upload_worker(self) -> None:
        while not self._upload_stopping.is_set():
            try:
                job = self._upload_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if self._upload_stopping.is_set():
                    self._complete_upload(len(job.data))
                    return
                assert isinstance(job, _UploadJob)
                try:
                    self._client.upload_bytes(job.grant, job.data)
                except Exception as error:
                    self._retry_or_complete(job, error)
                else:
                    try:
                        self._schedule_status(job)
                    finally:
                        self._complete_upload(len(job.data))
            finally:
                self._upload_queue.task_done()

    def _schedule_status(self, job: _UploadJob) -> None:
        now = time.monotonic()
        first_delay = max(
            _seconds_until_expiration(job.grant.expires_at)
            + self._status_poll_interval,
            self._status_poll_interval,
        )
        with self._status_condition:
            if self._status_stopping:
                return
            if len(self._status_jobs) >= self._status_max_items:
                logger.debug(
                    "Arize blob status queue is full; verification will not be monitored for %s",
                    job.grant.reference,
                )
                return
            self._status_sequence += 1
            heapq.heappush(
                self._status_jobs,
                _StatusJob(
                    run_at=now + first_delay,
                    sequence=self._status_sequence,
                    reference=job.grant.reference,
                    destination=job.destination,
                    deadline=now + first_delay + self._status_timeout,
                ),
            )
            self._status_condition.notify_all()

    def _status_worker(self) -> None:
        while True:
            with self._status_condition:
                while not self._status_jobs and not self._status_stopping:
                    self._status_condition.wait()
                if self._status_stopping:
                    return
                job = self._status_jobs[0]
                remaining = job.run_at - time.monotonic()
                if remaining > 0:
                    self._status_condition.wait(timeout=remaining)
                    continue
                heapq.heappop(self._status_jobs)

            try:
                status = self._client.get_status(
                    job.reference,
                    job.destination,
                )
            except Exception as error:
                if _is_retryable_status_error(error):
                    logger.debug(
                        "Arize blob status check failed for %s (%s)",
                        job.reference,
                        type(error).__name__,
                    )
                    self._reschedule_status(job)
                else:
                    logger.warning(
                        "Arize blob status monitoring stopped for %s (%s)",
                        job.reference,
                        type(error).__name__,
                    )
                continue

            if status == BlobStatus.SUCCESSFUL:
                continue
            if status == BlobStatus.FAILED:
                logger.warning(
                    "Arize blob verification failed for %s; the reference may be unavailable",
                    job.reference,
                )
                continue
            self._reschedule_status(job)

    def _reschedule_status(self, job: _StatusJob) -> None:
        now = time.monotonic()
        if now >= job.deadline:
            logger.warning(
                "Arize blob verification timed out for %s",
                job.reference,
            )
            return
        with self._status_condition:
            if self._status_stopping:
                return
            if len(self._status_jobs) >= self._status_max_items:
                return
            self._status_sequence += 1
            heapq.heappush(
                self._status_jobs,
                _StatusJob(
                    run_at=now + max(self._status_poll_interval, 0.1),
                    sequence=self._status_sequence,
                    reference=job.reference,
                    destination=job.destination,
                    deadline=job.deadline,
                ),
            )
            self._status_condition.notify_all()

    def _retry_or_complete(
        self,
        job: _UploadJob,
        error: Exception,
    ) -> None:
        if self._upload_stopping.is_set():
            self._complete_upload(len(job.data))
            return
        if job.attempt >= self._max_upload_attempts:
            logger.warning(
                "Arize blob upload failed for %s after %d attempt(s) (%s)",
                job.grant.reference,
                job.attempt,
                type(error).__name__,
            )
            self._complete_upload(len(job.data))
            return

        try:
            result = self._client.request_upload(job.metadata, job.destination)
        except Exception as refresh_error:
            logger.warning(
                "Arize blob upload retry failed for %s (%s)",
                job.grant.reference,
                type(refresh_error).__name__,
            )
            self._complete_upload(len(job.data))
            return

        if isinstance(result, ExistingBlobReference):
            if result.reference != job.grant.reference:
                logger.warning(
                    "Arize blob upload retry returned a different reference; retry abandoned"
                )
            self._complete_upload(len(job.data))
            return
        if result.reference != job.grant.reference:
            logger.warning(
                "Arize blob upload retry returned a different reference; retry abandoned"
            )
            self._complete_upload(len(job.data))
            return

        retry = _UploadJob(
            grant=result,
            metadata=job.metadata,
            data=job.data,
            destination=job.destination,
            attempt=job.attempt + 1,
        )
        with self._lifecycle_lock:
            if not self._accepting or self._upload_stopping.is_set():
                self._complete_upload(len(job.data))
                return
            try:
                self._upload_queue.put_nowait(retry)
            except queue.Full:
                logger.warning(
                    "Arize blob upload retry queue is full for %s",
                    job.grant.reference,
                )
                self._complete_upload(len(job.data))

    def _cancel_queued_uploads(self) -> None:
        while True:
            try:
                job = self._upload_queue.get_nowait()
            except queue.Empty:
                return
            try:
                self._complete_upload(len(job.data))
            finally:
                self._upload_queue.task_done()

    def _warn_missing_destination_once(self) -> None:
        with self._lifecycle_lock:
            if self._missing_destination_warned:
                return
            self._missing_destination_warned = True
        logger.warning(
            "Arize blob uploads require a space and project from configuration or the active routing context; oversized content will be redacted"
        )

    def _complete_upload(self, size: int) -> None:
        self._byte_budget.release(size)
        with self._pending_condition:
            self._pending_uploads -= 1
            self._pending_condition.notify_all()


def _md5_base64(data: bytes) -> str:
    # The Arize upload API requires Content-MD5 for transport integrity and deduplication;
    # it is not used as a security primitive.
    try:
        digest = hashlib.md5(data, usedforsecurity=False).digest()  # noqa: S324
    except TypeError:
        digest = hashlib.md5(data).digest()  # noqa: S324
    return base64.b64encode(digest).decode("ascii")


def _seconds_until_expiration(expires_at: Optional[str]) -> float:
    if not isinstance(expires_at, str) or not expires_at:
        return 0.0
    try:
        normalized = _RFC3339_EXCESS_FRACTION.sub(r"\1", expires_at)
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        expiration = datetime.fromisoformat(normalized)
        if expiration.tzinfo is None:
            return 0.0
        return max(expiration.timestamp() - time.time(), 0.0)
    except (OSError, OverflowError, ValueError):
        return 0.0


def _is_retryable_status_error(error: Exception) -> bool:
    if isinstance(error, BlobTransportError):
        return True
    if isinstance(error, BlobHTTPError):
        return error.status_code in (408, 429) or 500 <= error.status_code < 600
    return False
