"""File storage service for chat file uploads.

Supports local filesystem storage.
Files are organized per-user: {storage_root}/{user_id}/{uuid}_{filename}
"""

import logging
import re
import uuid
from abc import ABC, abstractmethod
from asyncio import to_thread
from datetime import UTC, datetime
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
    "video/mp4",
    "video/webm",
    "video/quicktime",
}

IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

MAX_UPLOAD_SIZE = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024


def classify_file(mime_type: str, filename: str) -> str:
    """Classify file type based on MIME type and extension."""
    if mime_type in IMAGE_MIME_TYPES:
        return "image"
    if mime_type == "application/pdf" or filename.lower().endswith(".pdf"):
        return "pdf"
    if mime_type.startswith("video/"):
        return "video"
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
    async def save(
        self,
        user_id: str,
        filename: str,
        data: bytes,
        content_type: str | None = None,
    ) -> str:
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

    async def get_metadata(self, storage_path: str) -> dict[str, Any]:
        """Return object metadata such as size and content type."""
        raise NotImplementedError("Object metadata is not supported by this storage")

    async def create_presigned_upload_url(
        self,
        user_id: str,
        filename: str,
        content_type: str,
        expires_in: int,
    ) -> tuple[str, str, dict[str, str]]:
        """Create a direct-upload URL, key, and required headers."""
        raise NotImplementedError("Presigned uploads require an S3-compatible storage")

    async def create_presigned_download_url(
        self,
        storage_path: str,
        filename: str,
        expires_in: int,
    ) -> str:
        """Create a direct-download URL."""
        raise NotImplementedError("Presigned downloads require an S3-compatible storage")

    async def cleanup_orphans(
        self,
        referenced_keys: set[str],
        prefix: str,
        older_than: datetime,
    ) -> int:
        """Delete old objects that are not referenced by the database."""
        raise NotImplementedError("Orphan cleanup requires an S3-compatible storage")


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

    async def save(
        self,
        user_id: str,
        filename: str,
        data: bytes,
        content_type: str | None = None,
    ) -> str:
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

    async def get_metadata(self, storage_path: str) -> dict[str, Any]:
        """Read local file metadata without loading its content."""
        file_path = self._resolve_safe_path(storage_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {storage_path}")
        stat = file_path.stat()
        return {
            "size": stat.st_size,
            "content_type": "application/octet-stream",
            "last_modified": datetime.fromtimestamp(stat.st_mtime, UTC),
        }


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
        visibility: str = "private",
        key_prefix: str = "uploads",
    ) -> None:
        if not all((account_id, access_key_id, secret_access_key, bucket_name)):
            raise ValueError(
                "R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, "
                "and R2_BUCKET_NAME are required when STORAGE_BACKEND=r2"
            )

        import boto3

        self.bucket_name = bucket_name
        self.public_url = public_url.rstrip("/") if public_url else None
        self.visibility = visibility
        self.key_prefix = key_prefix.strip("/")
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )

    async def save(
        self,
        user_id: str,
        filename: str,
        data: bytes,
        content_type: str | None = None,
    ) -> str:
        """Upload file bytes and return the object key."""
        key = self._make_key(user_id, filename)
        params: dict[str, Any] = {
            "Bucket": self.bucket_name,
            "Key": key,
            "Body": data,
        }
        if content_type:
            params["ContentType"] = content_type
        await to_thread(
            self.client.put_object,
            **params,
        )
        return key

    def _make_key(self, user_id: str, filename: str) -> str:
        """Create a collision-resistant, user-scoped object key."""
        user_parts = [
            _sanitize_filename(part) for part in user_id.split("/") if part
        ]
        return (
            f"{self.key_prefix}/{'/'.join(user_parts)}/"
            f"{make_storage_filename(filename)}"
        )

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

    async def get_metadata(self, storage_path: str) -> dict[str, Any]:
        """Read object metadata without downloading its content."""
        response: dict[str, Any] = await to_thread(
            self.client.head_object,
            Bucket=self.bucket_name,
            Key=storage_path,
        )
        return {
            "size": response.get("ContentLength", 0),
            "content_type": response.get("ContentType", "application/octet-stream"),
            "etag": str(response.get("ETag", "")).strip('"'),
            "last_modified": response.get("LastModified"),
            "metadata": response.get("Metadata", {}),
        }

    async def create_presigned_upload_url(
        self,
        user_id: str,
        filename: str,
        content_type: str,
        expires_in: int,
    ) -> tuple[str, str, dict[str, str]]:
        """Create a presigned PUT URL for direct browser-to-R2 upload."""
        key = self._make_key(user_id, filename)
        url = await to_thread(
            self.client.generate_presigned_url,
            "put_object",
            Params={
                "Bucket": self.bucket_name,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=expires_in,
        )
        return url, key, {"Content-Type": content_type}

    async def create_presigned_download_url(
        self,
        storage_path: str,
        filename: str,
        expires_in: int,
    ) -> str:
        """Create a private download URL or return a configured public URL."""
        if self.visibility == "public" and self.public_url:
            return f"{self.public_url}/{storage_path.lstrip('/')}"
        return await to_thread(
            self.client.generate_presigned_url,
            "get_object",
            Params={
                "Bucket": self.bucket_name,
                "Key": storage_path,
                "ResponseContentDisposition": (
                    f'attachment; filename="{filename.replace(chr(34), "")}"'
                ),
            },
            ExpiresIn=expires_in,
        )

    async def cleanup_orphans(
        self,
        referenced_keys: set[str],
        prefix: str,
        older_than: datetime,
    ) -> int:
        """Delete unreferenced objects older than the safety threshold."""
        paginator = self.client.get_paginator("list_objects_v2")
        pages = await to_thread(
            lambda: list(paginator.paginate(Bucket=self.bucket_name, Prefix=prefix))
        )
        candidates = [
            item["Key"]
            for page in pages
            for item in page.get("Contents", [])
            if item["Key"] not in referenced_keys
            and not item["Key"].startswith(f"{prefix.rstrip('/')}/avatars/")
            and item.get("LastModified", datetime.now(UTC)) < older_than
        ]
        deleted = 0
        for start in range(0, len(candidates), 1000):
            batch = candidates[start : start + 1000]
            await to_thread(
                self.client.delete_objects,
                Bucket=self.bucket_name,
                Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
            )
            deleted += len(batch)
        return deleted

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
            visibility=settings.R2_BUCKET_VISIBILITY,
            key_prefix=settings.R2_KEY_PREFIX,
        )
    media_dir = getattr(settings, "MEDIA_DIR", "media")
    return LocalFileStorage(base_dir=media_dir)
