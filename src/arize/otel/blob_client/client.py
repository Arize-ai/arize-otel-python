from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional
from urllib.parse import urlsplit, urlunsplit

import requests
from opentelemetry import context as context_api

from .errors import (
    BlobHTTPError,
    BlobProtocolError,
    BlobTransportError,
    BlobUploadError,
)
from .types import (
    BlobDestination,
    BlobGrant,
    BlobMetadata,
    BlobStatus,
    BlobUploadResult,
    ExistingBlobReference,
)

# These paths retain the backend RPC names while the public SDK API uses the
# broader "blob" terminology.
_UPLOAD_PATH = "media_upload"
_STATUS_PATH = "media_upload_status"


@contextmanager
def _suppress_instrumentation() -> Iterator[None]:
    context = context_api.set_value(
        context_api._SUPPRESS_INSTRUMENTATION_KEY,  # type: ignore[attr-defined]
        True,
    )
    token = context_api.attach(context)
    try:
        yield
    finally:
        context_api.detach(token)


class ArizeBlobClient:
    """HTTP/JSON client for the Arize blob upload API."""

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str,
        request_timeout_seconds: float = 1.0,
        upload_timeout_seconds: float = 30.0,
        verify: Any = True,
        upload_verify: Any = True,
        control_session: Optional[requests.Session] = None,
        upload_session: Optional[requests.Session] = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        if upload_timeout_seconds <= 0:
            raise ValueError("upload_timeout_seconds must be positive")

        self._api_key = api_key
        self._base_endpoint = _normalize_endpoint(endpoint)
        self._request_timeout_seconds = request_timeout_seconds
        self._upload_timeout_seconds = upload_timeout_seconds
        self._control_verify = verify
        self._upload_verify = upload_verify
        # Do not share a requests.Session across application and worker
        # threads. The module-level helpers create a short-lived session per
        # call; callers can still inject sessions for testing or custom HTTP
        # behavior when they own the synchronization and lifecycle.
        self._control_session = control_session
        self._upload_session = upload_session

    def request_upload(
        self,
        metadata: BlobMetadata,
        destination: BlobDestination,
    ) -> BlobUploadResult:
        payload = {
            "spaceId": destination.space_id,
            "externalModelId": destination.project_name,
            "item": {
                "mimeType": metadata.mime_type,
                "declaredSizeBytes": metadata.size_bytes,
                "checksum": metadata.md5_base64,
            },
        }
        response = self._post(
            _UPLOAD_PATH,
            destination,
            payload,
        )
        body = _response_json(response)

        reference = body.get("reference")
        if isinstance(reference, str) and reference:
            _validate_reference(reference)
            return ExistingBlobReference(reference=reference)

        grant = body.get("grant")
        if not isinstance(grant, dict):
            raise BlobProtocolError(
                "blob response contained neither a grant nor a reference"
            )
        return _parse_grant(grant)

    def upload_bytes(self, grant: BlobGrant, data: bytes) -> None:
        if grant.method.upper() != "PUT":
            raise BlobProtocolError(f"unsupported blob upload method {grant.method!r}")
        try:
            with _suppress_instrumentation():
                request = (
                    self._upload_session.request
                    if self._upload_session is not None
                    else requests.request
                )
                response = request(
                    method="PUT",
                    url=grant.upload_url,
                    data=data,
                    headers=dict(grant.required_headers),
                    timeout=self._upload_timeout_seconds,
                    allow_redirects=False,
                    verify=self._upload_verify,
                )
        except requests.RequestException as error:
            raise BlobTransportError("presigned blob upload failed") from error

        if not 200 <= response.status_code < 300:
            raise BlobUploadError(
                f"presigned blob upload failed with HTTP {response.status_code}"
            )

    def get_status(
        self,
        reference: str,
        destination: BlobDestination,
    ) -> BlobStatus:
        _validate_reference(reference)
        response = self._post(
            _STATUS_PATH,
            destination,
            {"reference": reference},
        )
        body = _response_json(response)
        return _parse_status(body.get("status"))

    def close(self) -> None:
        # Injected sessions are caller-owned. Module-level requests do not
        # leave a persistent session to close.
        return None

    def _post(
        self,
        path: str,
        destination: BlobDestination,
        payload: Dict[str, Any],
    ) -> requests.Response:
        if not destination.space_id:
            raise ValueError("space_id is required")
        if not destination.project_name:
            raise ValueError("project_name is required")

        headers = {
            "Grpc-Metadata-authorization": self._api_key,
            "Grpc-Metadata-arize-space-id": destination.space_id,
            "Grpc-Metadata-arize-interface": "otel",
        }
        try:
            with _suppress_instrumentation():
                post = (
                    self._control_session.post
                    if self._control_session is not None
                    else requests.post
                )
                response = post(
                    f"{self._base_endpoint}/{path}",
                    json=payload,
                    headers=headers,
                    timeout=self._request_timeout_seconds,
                    allow_redirects=False,
                    verify=self._control_verify,
                )
        except requests.RequestException as error:
            raise BlobTransportError("Arize blob request failed") from error

        if 200 <= response.status_code < 300:
            return response

        message = _error_message(response)
        raise BlobHTTPError(
            response.status_code,
            message,
            retry_after=response.headers.get("Retry-After"),
        )


def _normalize_endpoint(endpoint: str) -> str:
    if not endpoint:
        raise ValueError("endpoint is required")
    parsed = urlsplit(endpoint)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("endpoint must be an absolute HTTP(S) URL")

    path = parsed.path.rstrip("/")
    if path.endswith("/v1/traces"):
        path = path[: -len("/traces")]
    elif not path:
        path = "/v1"

    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _response_json(response: requests.Response) -> Dict[str, Any]:
    try:
        body = response.json()
    except ValueError as error:
        raise BlobProtocolError("Arize returned invalid JSON") from error
    if not isinstance(body, dict):
        raise BlobProtocolError("Arize returned a non-object JSON response")
    return body


def _error_message(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return "request failed"
    if isinstance(body, dict) and isinstance(body.get("message"), str):
        return body["message"][:512]
    return "request failed"


def _parse_grant(grant: Dict[str, Any]) -> BlobGrant:
    reference = grant.get("reference")
    upload_url = grant.get("uploadUrl")
    method = grant.get("httpMethod")
    required_headers = grant.get("requiredHeaders")
    expires_at = grant.get("expiresAt")

    if not isinstance(reference, str) or not reference:
        raise BlobProtocolError("blob grant is missing a reference")
    _validate_reference(reference)
    if not isinstance(upload_url, str) or not upload_url:
        raise BlobProtocolError("blob grant is missing an upload URL")
    parsed_url = urlsplit(upload_url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        raise BlobProtocolError("blob grant upload URL is not HTTP(S)")
    if not isinstance(method, str) or not method:
        raise BlobProtocolError("blob grant is missing an HTTP method")
    if required_headers is None:
        required_headers = {}
    if not isinstance(required_headers, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in required_headers.items()
    ):
        raise BlobProtocolError("blob grant has invalid required headers")
    if expires_at is not None and not isinstance(expires_at, str):
        raise BlobProtocolError("blob grant has an invalid expiration")

    return BlobGrant(
        reference=reference,
        upload_url=upload_url,
        method=method,
        required_headers=dict(required_headers),
        expires_at=expires_at,
    )


def _validate_reference(reference: str) -> None:
    if not reference.startswith("arize://") or len(reference) == len("arize://"):
        raise BlobProtocolError("Arize returned an invalid blob reference")


def _parse_status(value: Any) -> BlobStatus:
    if isinstance(value, int):
        statuses = {
            1: BlobStatus.REQUESTED,
            2: BlobStatus.SUCCESSFUL,
            3: BlobStatus.FAILED,
        }
        if value in statuses:
            return statuses[value]
    if isinstance(value, str):
        normalized = value.upper()
        prefix = "MEDIA_FILE_STATUS_"
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
        try:
            return BlobStatus(normalized.lower())
        except ValueError:
            pass
    raise BlobProtocolError("Arize returned an unknown blob status")
