from typing import Any, Dict, List, Optional

import pytest

from arize.otel.blob_client import (
    ExistingBlobReference,
    BlobDestination,
    BlobMetadata,
    BlobStatus,
    BlobGrant,
    BlobHTTPError,
    ArizeBlobClient,
)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: Any,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self) -> Any:
        return self._payload


class FakeSession:
    def __init__(self, responses: List[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: List[Dict[str, Any]] = []
        self.closed = False

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"operation": "post", "url": url, **kwargs})
        return self._responses.pop(0)

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(
            {"operation": "request", "method": method, "url": url, **kwargs}
        )
        return self._responses.pop(0)

    def close(self) -> None:
        self.closed = True


DESTINATION = BlobDestination(
    space_id="space-id",
    project_name="project-name",
)
METADATA = BlobMetadata(
    mime_type="image/png",
    size_bytes=3,
    md5_base64="v/E5+gWsWD9oWlI6s9EQoA==",
)


def test_request_upload_parses_grant_and_sends_gateway_metadata() -> None:
    control = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "grant": {
                        "reference": "arize://reference-id",
                        "uploadUrl": "https://storage.example/upload?signature=secret",
                        "requiredHeaders": {
                            "Content-MD5": METADATA.md5_base64,
                            "Content-Type": "image/png",
                        },
                        "httpMethod": "PUT",
                        "expiresAt": "2026-07-29T22:00:00Z",
                    }
                },
            )
        ]
    )
    client = ArizeBlobClient(
        api_key="api-key",
        endpoint="https://otlp.arize.com/v1",
        verify=False,
        control_session=control,  # type: ignore[arg-type]
        upload_session=FakeSession([]),  # type: ignore[arg-type]
    )

    result = client.request_upload(METADATA, DESTINATION)

    assert isinstance(result, BlobGrant)
    assert result.reference == "arize://reference-id"
    call = control.calls[0]
    assert call["url"] == "https://otlp.arize.com/v1/media_upload"
    assert call["headers"] == {
        "Grpc-Metadata-authorization": "api-key",
        "Grpc-Metadata-arize-space-id": "space-id",
        "Grpc-Metadata-arize-interface": "otel",
    }
    assert call["json"] == {
        "spaceId": "space-id",
        "externalModelId": "project-name",
        "item": {
            "mimeType": "image/png",
            "declaredSizeBytes": 3,
            "checksum": METADATA.md5_base64,
        },
    }
    assert call["allow_redirects"] is False
    assert call["verify"] is False
    assert call["timeout"] == 1.0


def test_request_upload_parses_existing_reference() -> None:
    control = FakeSession([FakeResponse(200, {"reference": "arize://reference-id"})])
    client = ArizeBlobClient(
        api_key="api-key",
        endpoint="https://otlp.arize.com/v1/traces",
        control_session=control,  # type: ignore[arg-type]
        upload_session=FakeSession([]),  # type: ignore[arg-type]
    )

    result = client.request_upload(METADATA, DESTINATION)

    assert result == ExistingBlobReference(reference="arize://reference-id")
    assert control.calls[0]["url"] == ("https://otlp.arize.com/v1/media_upload")


def test_upload_bytes_uses_only_required_headers_and_disables_redirects() -> None:
    upload = FakeSession([FakeResponse(200, {})])
    client = ArizeBlobClient(
        api_key="api-key",
        endpoint="https://otlp.arize.com/v1",
        verify=False,
        upload_verify=True,
        control_session=FakeSession([]),  # type: ignore[arg-type]
        upload_session=upload,  # type: ignore[arg-type]
    )
    grant = BlobGrant(
        reference="arize://reference-id",
        upload_url="https://storage.example/upload?signature=secret",
        method="PUT",
        required_headers={"Content-Type": "image/png"},
    )

    client.upload_bytes(grant, b"png")

    call = upload.calls[0]
    assert call["method"] == "PUT"
    assert call["headers"] == {"Content-Type": "image/png"}
    assert "authorization" not in {key.lower() for key in call["headers"]}
    assert call["data"] == b"png"
    assert call["allow_redirects"] is False
    assert call["verify"] is True


@pytest.mark.parametrize(
    ("wire_status", "expected"),
    [
        ("MEDIA_FILE_STATUS_REQUESTED", BlobStatus.REQUESTED),
        ("MEDIA_FILE_STATUS_SUCCESSFUL", BlobStatus.SUCCESSFUL),
        (3, BlobStatus.FAILED),
    ],
)
def test_get_status_parses_proto_json_status(
    wire_status: Any,
    expected: BlobStatus,
) -> None:
    control = FakeSession([FakeResponse(200, {"status": wire_status})])
    client = ArizeBlobClient(
        api_key="api-key",
        endpoint="https://otlp.arize.com/v1",
        control_session=control,  # type: ignore[arg-type]
        upload_session=FakeSession([]),  # type: ignore[arg-type]
    )

    assert client.get_status("arize://reference-id", DESTINATION) == expected


def test_not_found_uses_generic_http_error() -> None:
    control = FakeSession(
        [
            FakeResponse(
                404,
                {
                    "message": "no active project with this external_model_id in the space"
                },
            )
        ]
    )
    client = ArizeBlobClient(
        api_key="api-key",
        endpoint="https://otlp.arize.com/v1",
        control_session=control,  # type: ignore[arg-type]
        upload_session=FakeSession([]),  # type: ignore[arg-type]
    )

    with pytest.raises(BlobHTTPError) as exc_info:
        client.request_upload(METADATA, DESTINATION)

    assert exc_info.value.status_code == 404
