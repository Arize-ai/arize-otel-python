from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Union


@dataclass(frozen=True)
class BlobDestination:
    space_id: str
    project_name: str


@dataclass(frozen=True)
class BlobMetadata:
    mime_type: str
    size_bytes: int
    md5_base64: str


@dataclass(frozen=True)
class BlobGrant:
    reference: str
    upload_url: str = field(repr=False)
    method: str
    required_headers: Dict[str, str] = field(repr=False)
    expires_at: Optional[str] = None


@dataclass(frozen=True)
class ExistingBlobReference:
    reference: str


BlobUploadResult = Union[BlobGrant, ExistingBlobReference]


class BlobStatus(str, Enum):
    REQUESTED = "requested"
    SUCCESSFUL = "successful"
    FAILED = "failed"
