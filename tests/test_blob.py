import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import List

import pytest

import arize.otel.blob as blob_module
from arize.otel import ArizeBlobUploader, set_routing_context
from arize.otel.blob_client import (
    ExistingBlobReference,
    BlobDestination,
    BlobMetadata,
    BlobStatus,
    BlobGrant,
    BlobHTTPError,
    BlobTransportError,
    BlobUploadResult,
)


@dataclass(frozen=True)
class FakeBlob:
    data: bytes
    mime_type: str


class FakeBlobClient:
    def __init__(self, result: BlobUploadResult) -> None:
        self.result = result
        self.destinations: List[BlobDestination] = []
        self.metadata: List[BlobMetadata] = []
        self.uploaded = threading.Event()
        self.status_checked = threading.Event()
        self.closed = False
        self.upload_calls = 0
        self.upload_failures_remaining = 0
        self.statuses: List[BlobStatus] = [BlobStatus.SUCCESSFUL]
        self._lock = threading.Lock()

    def request_upload(
        self,
        metadata: BlobMetadata,
        destination: BlobDestination,
    ) -> BlobUploadResult:
        self.metadata.append(metadata)
        self.destinations.append(destination)
        return self.result

    def upload_bytes(self, grant: BlobGrant, data: bytes) -> None:
        assert data == b"png"
        with self._lock:
            self.upload_calls += 1
            if self.upload_failures_remaining:
                self.upload_failures_remaining -= 1
                raise RuntimeError("upload failed")
            self.uploaded.set()

    def get_status(
        self,
        reference: str,
        destination: BlobDestination,
    ) -> BlobStatus:
        self.status_checked.set()
        with self._lock:
            if len(self.statuses) > 1:
                return self.statuses.pop(0)
            return self.statuses[0]

    def close(self) -> None:
        self.closed = True


def _grant() -> BlobGrant:
    return BlobGrant(
        reference="arize://reference-id",
        upload_url="https://storage.example/upload?signature=secret",
        method="PUT",
        required_headers={"Content-Type": "image/png"},
    )


def _uploader(
    client: FakeBlobClient,
    *,
    queue_max_bytes: int = 1024,
) -> ArizeBlobUploader:
    return ArizeBlobUploader(
        space_id="space-id",
        project_name="project-name",
        client=client,
        queue_max_bytes=queue_max_bytes,
        status_poll_interval_seconds=0,
        status_timeout_seconds=1,
    )


def test_upload_returns_reference_before_background_put_finishes() -> None:
    client = FakeBlobClient(_grant())
    uploader = _uploader(client)

    reference = uploader.upload(FakeBlob(data=b"png", mime_type="image/png"))

    assert reference == "arize://reference-id"
    assert client.uploaded.wait(timeout=1)
    assert client.status_checked.wait(timeout=1)
    assert client.metadata[0].size_bytes == 3
    assert client.metadata[0].md5_base64 == "v/E5+gWsWD9oWlI6s9EQoA=="
    uploader.shutdown()
    assert client.closed


def test_existing_reference_skips_background_upload() -> None:
    client = FakeBlobClient(ExistingBlobReference(reference="arize://reference-id"))
    uploader = _uploader(client)

    reference = uploader.upload(FakeBlob(data=b"png", mime_type="image/png"))

    assert reference == "arize://reference-id"
    assert not client.uploaded.is_set()
    uploader.shutdown()


def test_queue_byte_budget_rejects_before_requesting_grant() -> None:
    client = FakeBlobClient(_grant())
    uploader = _uploader(client, queue_max_bytes=2)

    reference = uploader.upload(FakeBlob(data=b"png", mime_type="image/png"))

    assert reference is None
    assert not client.metadata
    uploader.shutdown()


def test_dynamic_routing_context_is_captured_before_enqueue() -> None:
    client = FakeBlobClient(ExistingBlobReference(reference="arize://reference-id"))
    uploader = _uploader(client)

    with set_routing_context("dynamic-space", "dynamic-project"):
        uploader.upload(FakeBlob(data=b"png", mime_type="image/png"))

    assert client.destinations == [
        BlobDestination(
            space_id="dynamic-space",
            project_name="dynamic-project",
        )
    ]
    uploader.shutdown()


def test_dynamic_routing_does_not_require_a_static_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ARIZE_SPACE_ID", raising=False)
    monkeypatch.delenv("ARIZE_PROJECT_NAME", raising=False)
    client = FakeBlobClient(ExistingBlobReference(reference="arize://reference-id"))
    uploader = ArizeBlobUploader(client=client)

    with set_routing_context("dynamic-space", "dynamic-project"):
        reference = uploader.upload(FakeBlob(data=b"png", mime_type="image/png"))

    assert reference == "arize://reference-id"
    assert client.destinations == [
        BlobDestination(
            space_id="dynamic-space",
            project_name="dynamic-project",
        )
    ]
    uploader.shutdown()


def test_item_limit_includes_grant_requests_in_flight() -> None:
    client = FakeBlobClient(_grant())
    grant_started = threading.Event()
    release_grant = threading.Event()
    original_request_upload = client.request_upload

    def blocking_request_upload(
        metadata: BlobMetadata,
        destination: BlobDestination,
    ) -> BlobUploadResult:
        grant_started.set()
        assert release_grant.wait(timeout=1)
        return original_request_upload(metadata, destination)

    client.request_upload = blocking_request_upload  # type: ignore[method-assign]
    uploader = ArizeBlobUploader(
        space_id="space-id",
        project_name="project-name",
        client=client,
        queue_max_items=1,
        status_poll_interval_seconds=0,
        status_timeout_seconds=1,
    )
    references: List[object] = []
    thread = threading.Thread(
        target=lambda: references.append(
            uploader.upload(FakeBlob(data=b"png", mime_type="image/png"))
        )
    )
    thread.start()
    assert grant_started.wait(timeout=1)

    rejected = uploader.upload(FakeBlob(data=b"png", mime_type="image/png"))
    release_grant.set()
    thread.join(timeout=1)

    assert rejected is None
    assert not thread.is_alive()
    assert references == ["arize://reference-id"]
    assert len(client.metadata) == 1
    uploader.shutdown()


def test_failed_put_requests_fresh_grant_and_retries() -> None:
    client = FakeBlobClient(_grant())
    client.upload_failures_remaining = 1
    uploader = _uploader(client)

    reference = uploader.upload(FakeBlob(data=b"png", mime_type="image/png"))

    assert reference == "arize://reference-id"
    assert client.uploaded.wait(timeout=1)
    assert client.status_checked.wait(timeout=1)
    uploader.shutdown()
    assert client.upload_calls == 2
    assert len(client.metadata) == 2


def test_failed_verification_does_not_retain_bytes_for_reupload() -> None:
    client = FakeBlobClient(_grant())
    client.statuses = [
        BlobStatus.FAILED,
        BlobStatus.SUCCESSFUL,
    ]
    uploader = _uploader(client)

    reference = uploader.upload(FakeBlob(data=b"png", mime_type="image/png"))

    assert reference == "arize://reference-id"
    assert client.status_checked.wait(timeout=1)
    uploader.shutdown()
    assert client.upload_calls == 1
    assert len(client.metadata) == 1
    assert client.closed


def test_status_poll_waits_for_grant_expiration_and_shutdown_does_not_wait() -> None:
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    client = FakeBlobClient(replace(_grant(), expires_at=expires_at))
    uploader = _uploader(client)

    reference = uploader.upload(FakeBlob(data=b"png", mime_type="image/png"))

    assert reference == "arize://reference-id"
    assert client.uploaded.wait(timeout=1)
    assert not client.status_checked.wait(timeout=0.05)
    uploader.shutdown(timeout_sec=1)
    assert client.closed


def test_status_poll_reschedules_at_fixed_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeBlobClient(_grant())
    uploader = ArizeBlobUploader(
        space_id="space-id",
        project_name="project-name",
        client=client,
        status_poll_interval_seconds=7,
        status_timeout_seconds=60,
    )
    monkeypatch.setattr(blob_module.time, "monotonic", lambda: 100.0)
    job = blob_module._StatusJob(
        run_at=100.0,
        sequence=1,
        reference="arize://reference-id",
        destination=BlobDestination("space-id", "project-name"),
        deadline=200.0,
    )

    uploader._reschedule_status(job)

    assert uploader._status_jobs[0].run_at == 107.0
    uploader.shutdown()


def test_checksum_failure_is_contained_and_releases_queue_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeBlobClient(ExistingBlobReference(reference="arize://reference-id"))
    uploader = _uploader(client, queue_max_bytes=3)
    original_md5 = blob_module._md5_base64

    def fail_md5(_: bytes) -> str:
        raise ValueError("MD5 disabled")

    monkeypatch.setattr(blob_module, "_md5_base64", fail_md5)

    rejected = uploader.upload(FakeBlob(data=b"png", mime_type="image/png"))
    monkeypatch.setattr(blob_module, "_md5_base64", original_md5)
    accepted = uploader.upload(FakeBlob(data=b"png", mime_type="image/png"))

    assert rejected is None
    assert accepted == "arize://reference-id"
    uploader.shutdown()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (BlobTransportError("network"), True),
        (BlobHTTPError(408, "timeout"), True),
        (BlobHTTPError(429, "limited"), True),
        (BlobHTTPError(503, "unavailable"), True),
        (BlobHTTPError(400, "invalid"), False),
        (BlobHTTPError(401, "unauthenticated"), False),
        (BlobHTTPError(403, "denied"), False),
        (BlobHTTPError(404, "not found"), False),
    ],
)
def test_status_error_retry_classification(
    error: Exception,
    expected: bool,
) -> None:
    assert blob_module._is_retryable_status_error(error) is expected


def test_grant_expiration_accepts_protojson_nanoseconds() -> None:
    future = datetime.now(timezone.utc) + timedelta(minutes=1)
    expires_at = future.strftime("%Y-%m-%dT%H:%M:%S") + ".123456789Z"

    delay = blob_module._seconds_until_expiration(expires_at)

    assert 0 < delay <= 61
