from typing import Optional


class BlobClientError(Exception):
    """Base error for Arize blob operations."""


class BlobTransportError(BlobClientError):
    """The Arize API or object store could not be reached."""


class BlobProtocolError(BlobClientError):
    """The Arize API returned an invalid blob response."""


class BlobHTTPError(BlobClientError):
    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        retry_after: Optional[str] = None,
    ) -> None:
        super().__init__(f"blob request failed with HTTP {status_code}: {message}")
        self.status_code = status_code
        self.retry_after = retry_after


class BlobUploadError(BlobClientError):
    """The object store rejected or failed a presigned upload."""
