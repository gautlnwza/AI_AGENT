"""Schemas for file upload operations."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class FileUploadResponse(BaseSchema):
    """Response after successful file upload."""

    id: UUID
    filename: str
    mime_type: str
    size: int
    file_type: str


class FileInfo(FileUploadResponse):
    """Full file metadata."""

    created_at: datetime
    user_id: UUID


class PresignedUploadRequest(BaseSchema):
    """Request for a direct browser-to-R2 upload URL."""

    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)


class PresignedUploadResponse(BaseSchema):
    """Details needed to upload directly to object storage."""

    upload_url: str
    storage_path: str
    expires_in: int
    headers: dict[str, str]


class CompleteUploadRequest(BaseSchema):
    """Metadata recorded after a direct upload completes."""

    storage_path: str = Field(min_length=1, max_length=500)
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=100)
    size: int = Field(ge=0)


class PresignedDownloadResponse(BaseSchema):
    """A temporary or public direct-download URL."""

    download_url: str
    expires_in: int
