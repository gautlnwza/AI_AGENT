"""File storage service for chat file uploads.

Supports local filesystem storage.
Files are organized per-user: {storage_root}/{user_id}/{uuid}_{filename}
"""

import logging
import re
import uuid
from abc import ABC, abstractmethod
from asyncio import to_thread
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/html",
    "text/css",
    "text/xml",
    "text/x-python",
    "text/javascript",
    "text/x-yaml",
    "application/json",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/x-yaml",
}

IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB


def classify_file(mime_type: str, filename: str) -> str:
    """Classify file type based on MIME type and extension."""
    if mime_type in IMAGE_MIME_TYPES:
        return "image"
    if mime_type == "application/pdf" or filename.lower().endswith(".pdf"):
        return "pdf"
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext == "docx" or "wordprocessingml" in mime_type:
        return "docx"
    return "text"


_UNSAFE_FILENAME_CHARS = re.compile(r"[^\w.\-]+")


def _sanitize_filename(filename: str) -> str:
    """Strip path separators, NULL bytes, and unsafe chars from a filename.

    The result is always a single path component with no traversal segments.
    Empty results fall back to ``"file"`` to preserve a non-empty name.
    """
    base = Path(filename).name.replace("\x00", "")
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", base).strip("._")
    return cleaned or "file"


def make_storage_filename(filename: str) -> str:
    """Create a unique storage filename to prevent collisions and path traversal."""
    safe = _sanitize_filename(filename)
    return f"{uuid.uuid4().hex[:12]}_{safe}"


class BaseFileStorage(ABC):
    """Abstract file storage backend."""

    @abstractmethod
    async def save(self, user_id: str, filename: str, data: bytes) -> str:
        """Save file and return storage path/key."""

    @abstractmethod
    async def load(self, storage_path: str) -> bytes:
        """Load file bytes by storage path."""

    @abstractmethod
    async def delete(self, storage_path: str) -> None:
        """Delete file by storage path."""

    def get_full_path(self, storage_path: str) -> Path | None:
        """Return absolute filesystem path if available (local storage only)."""
        return None  # pragma: no cover


class LocalFileStorage(BaseFileStorage):
    """Store files on local filesystem."""

    def __init__(self, base_dir: str | Path = "media"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_safe_path(self, storage_path: str) -> Path:
        """Resolve a storage path under base_dir, rejecting traversal attempts."""
        base = self.base_dir.resolve()
        candidate = (base / storage_path).resolve()
        if base != candidate and base not in candidate.parents:
            raise ValueError(f"Path escapes storage root: {storage_path}")
        return candidate

    async def save(self, user_id: str, filename: str, data: bytes) -> str:
        safe_user = _sanitize_filename(user_id)
        user_dir = self.base_dir / safe_user
        user_dir.mkdir(parents=True, exist_ok=True)
        storage_name = make_storage_filename(filename)
        file_path = user_dir / storage_name
        file_path.write_bytes(data)
        return f"{safe_user}/{storage_name}"

    async def load(self, storage_path: str) -> bytes:
        file_path = self._resolve_safe_path(storage_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {storage_path}")
        return file_path.read_bytes()

    async def delete(self, storage_path: str) -> None:
        file_path = self._resolve_safe_path(storage_path)
        if file_path.exists():
            file_path.unlink()

    def get_full_path(self, storage_path: str) -> Path | None:
        """Return absolute filesystem path for local files."""
        try:
            file_path = self._resolve_safe_path(storage_path)
        except ValueError:
            return None
        return file_path if file_path.exists() else None


class R2FileStorage(BaseFileStorage):
    """Store files in Cloudflare R2 through its S3-compatible API.

    boto3 is intentionally created only when this backend is selected, so local
    development does not require R2 credentials or make any network calls.
    Blocking boto3 calls are executed in a worker thread because the app is async.
    """

    def __init__(
        self,
        *,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket_name: str,
        endpoint_url: str | None = None,
        public_url: str | None = None,
    ) -> None:
        if not all((account_id, access_key_id, secret_access_key, bucket_name)):
            raise ValueError(
                "R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, "
                "and R2_BUCKET_NAME are required when STORAGE_BACKEND=r2"
            )

        import boto3

        self.bucket_name = bucket_name
        self.public_url = public_url.rstrip("/") if public_url else None
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )

    async def save(self, user_id: str, filename: str, data: bytes) -> str:
        """Upload file bytes and return the object key."""
        key = f"{_sanitize_filename(user_id)}/{make_storage_filename(filename)}"
        await to_thread(
            self.client.put_object,
            Bucket=self.bucket_name,
            Key=key,
            Body=data,
        )
        return key

    async def load(self, storage_path: str) -> bytes:
        """Download an object by key."""
        try:
            response: dict[str, Any] = await to_thread(
                self.client.get_object,
                Bucket=self.bucket_name,
                Key=storage_path,
            )
        except Exception as exc:
            error_code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if error_code in {"404", "NoSuchKey", "NotFound"}:
                raise FileNotFoundError(f"File not found: {storage_path}") from exc
            raise
        return await to_thread(response["Body"].read)

    async def delete(self, storage_path: str) -> None:
        """Delete an object by key."""
        await to_thread(
            self.client.delete_object,
            Bucket=self.bucket_name,
            Key=storage_path,
        )

    def get_full_path(self, storage_path: str) -> Path | None:
        """Return no filesystem path; R2 objects are served through the API."""
        return None

    def get_public_url(self, storage_path: str) -> str | None:
        """Return a public URL when an R2 custom/public domain is configured."""
        if not self.public_url:
            return None
        return f"{self.public_url}/{storage_path.lstrip('/')}"


def get_file_storage() -> BaseFileStorage:
    """Factory: create file storage backend based on settings."""
    if settings.STORAGE_BACKEND == "r2":
        return R2FileStorage(
            account_id=settings.R2_ACCOUNT_ID,
            access_key_id=settings.R2_ACCESS_KEY_ID,
            secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            bucket_name=settings.R2_BUCKET_NAME or settings.R2_BUCKET,
            endpoint_url=settings.R2_ENDPOINT_URL,
            public_url=settings.R2_PUBLIC_URL,
        )
    media_dir = getattr(settings, "MEDIA_DIR", "media")
    return LocalFileStorage(base_dir=media_dir)
