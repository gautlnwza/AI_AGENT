"""File upload and download endpoints for chat attachments."""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response

from app.api.deps import CurrentAdmin, CurrentUser, FileUploadSvc
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.schemas.file import (
    CompleteUploadRequest,
    FileInfo,
    FileUploadResponse,
    PresignedDownloadResponse,
    PresignedUploadRequest,
    PresignedUploadResponse,
)
from app.services.file_storage import ALLOWED_MIME_TYPES, get_file_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])


@router.post("/upload", response_model=FileUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file_upload_svc: FileUploadSvc,
    current_user: CurrentUser,
    file: UploadFile = File(...),
) -> Any:
    """Upload a file for use in chat."""
    data = await file.read()
    is_valid, error = file_upload_svc.validate_upload(file.content_type, len(data))
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    file_type = file_upload_svc.classify_file(file.content_type or "", file.filename or "unknown")
    parsed_content = await file_upload_svc.parse_content(data, file_type, file.content_type or "")
    storage = get_file_storage()
    storage_path = await storage.save(
        str(current_user.id), file.filename or "unknown", data, file.content_type
    )
    chat_file = await file_upload_svc.create_chat_file(
        user_id=current_user.id,
        filename=file.filename or "unknown",
        mime_type=file.content_type or "application/octet-stream",
        size=len(data),
        storage_path=storage_path,
        file_type=file_type,
        parsed_content=parsed_content,
    )

    return FileUploadResponse(
        id=chat_file.id,
        filename=chat_file.filename,
        mime_type=chat_file.mime_type,
        size=chat_file.size,
        file_type=chat_file.file_type,
    )


@router.post("/presigned-upload", response_model=PresignedUploadResponse)
async def create_presigned_upload(
    body: PresignedUploadRequest,
    current_user: CurrentUser,
) -> PresignedUploadResponse:
    """Create a short-lived direct upload URL for R2."""
    if body.content_type not in file_upload_allowed_types():
        raise HTTPException(status_code=400, detail="File type is not supported")
    storage = get_file_storage()
    try:
        url, storage_path, headers = await storage.create_presigned_upload_url(
            str(current_user.id),
            body.filename,
            body.content_type,
            settings.R2_PRESIGNED_URL_EXPIRE_SECONDS,
        )
    except NotImplementedError:
        raise HTTPException(status_code=400, detail="Presigned URLs require R2 storage") from None
    return PresignedUploadResponse(
        upload_url=url,
        storage_path=storage_path,
        expires_in=settings.R2_PRESIGNED_URL_EXPIRE_SECONDS,
        headers=headers,
    )


@router.post("/presigned-upload/complete", response_model=FileUploadResponse, status_code=201)
async def complete_presigned_upload(
    body: CompleteUploadRequest,
    file_upload_svc: FileUploadSvc,
    current_user: CurrentUser,
) -> FileUploadResponse:
    """Record metadata after the client finishes a direct R2 upload."""
    storage = get_file_storage()
    expected_prefix = f"{getattr(storage, 'key_prefix', 'uploads')}/{current_user.id}/"
    if not body.storage_path.startswith(expected_prefix):
        raise HTTPException(status_code=403, detail="Invalid storage path")
    is_valid, error = file_upload_svc.validate_upload(body.mime_type, body.size)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)
    try:
        metadata = await storage.get_metadata(body.storage_path)
    except (FileNotFoundError, KeyError):
        raise HTTPException(status_code=404, detail="Uploaded object was not found") from None
    if metadata.get("size") != body.size:
        raise HTTPException(status_code=400, detail="Uploaded file size does not match metadata")
    file_type = file_upload_svc.classify_file(body.mime_type, body.filename)
    chat_file = await file_upload_svc.create_chat_file(
        user_id=current_user.id,
        filename=body.filename,
        mime_type=body.mime_type,
        size=body.size,
        storage_path=body.storage_path,
        file_type=file_type,
    )
    return FileUploadResponse(
        id=chat_file.id,
        filename=chat_file.filename,
        mime_type=chat_file.mime_type,
        size=chat_file.size,
        file_type=chat_file.file_type,
    )


@router.get("/{file_id}")
async def download_file(
    file_id: UUID,
    file_upload_svc: FileUploadSvc,
    current_user: CurrentUser,
    disposition: str = "inline",
) -> Any:
    """Serve a file. Only the owner can access their files.

    By default the response is ``Content-Disposition: inline`` so PDFs, images
    and audio/video render directly inside an ``<iframe>`` / media tag (used
    by the chat file-preview panel). Pass ``?disposition=attachment`` to force
    the browser's download dialog (used by the explicit "Download" button).
    """
    try:
        chat_file = await file_upload_svc.get_user_file(file_id, current_user.id)
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
        ) from None

    storage = get_file_storage()
    file_path = storage.get_full_path(chat_file.storage_path)

    # FastAPI's ``FileResponse(filename=...)`` always uses ``attachment`` —
    # build the header manually so we can switch to ``inline`` for previews.
    mode = "attachment" if disposition == "attachment" else "inline"
    safe_name = chat_file.filename.replace('"', "")
    # The chat file-preview panel embeds this URL in an iframe (PDFs, HTML,
    # etc). Default ``X-Frame-Options: DENY`` from SecurityHeadersMiddleware
    # would break that, so opt this endpoint down to SAMEORIGIN. The CSP
    # ``frame-ancestors 'self'`` is the modern equivalent — browsers honor
    # whichever they recognize.
    headers = {
        "Content-Disposition": f'{mode}; filename="{safe_name}"',
        "X-Frame-Options": "SAMEORIGIN",
        "Content-Security-Policy": "frame-ancestors 'self'",
    }
    if file_path:
        return FileResponse(path=file_path, media_type=chat_file.mime_type, headers=headers)
    try:
        data = await storage.load(chat_file.storage_path)
    except (FileNotFoundError, KeyError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found") from None
    return Response(content=data, media_type=chat_file.mime_type, headers=headers)


@router.get("/{file_id}/download-url", response_model=PresignedDownloadResponse)
async def create_presigned_download(
    file_id: UUID,
    file_upload_svc: FileUploadSvc,
    current_user: CurrentUser,
) -> PresignedDownloadResponse:
    """Create a direct download URL after checking file ownership."""
    try:
        chat_file = await file_upload_svc.get_user_file(file_id, current_user.id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="File not found") from None
    storage = get_file_storage()
    try:
        url = await storage.create_presigned_download_url(
            chat_file.storage_path,
            chat_file.filename,
            settings.R2_PRESIGNED_URL_EXPIRE_SECONDS,
        )
    except NotImplementedError:
        raise HTTPException(status_code=400, detail="Presigned URLs require R2 storage") from None
    return PresignedDownloadResponse(
        download_url=url,
        expires_in=settings.R2_PRESIGNED_URL_EXPIRE_SECONDS,
    )


@router.get("/{file_id}/metadata")
async def get_object_metadata(
    file_id: UUID,
    file_upload_svc: FileUploadSvc,
    current_user: CurrentUser,
) -> dict[str, Any]:
    """Return database and object-storage metadata after ownership validation."""
    try:
        chat_file = await file_upload_svc.get_user_file(file_id, current_user.id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="File not found") from None
    storage = get_file_storage()
    try:
        object_metadata = await storage.get_metadata(chat_file.storage_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found in storage") from None
    return {
        "id": chat_file.id,
        "filename": chat_file.filename,
        "mime_type": chat_file.mime_type,
        "size": chat_file.size,
        "storage_path": chat_file.storage_path,
        "object": object_metadata,
    }


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: UUID,
    file_upload_svc: FileUploadSvc,
    current_user: CurrentUser,
) -> None:
    """Delete an owned object and its database metadata."""
    try:
        chat_file = await file_upload_svc.get_user_file(file_id, current_user.id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="File not found") from None
    storage = get_file_storage()
    await storage.delete(chat_file.storage_path)
    await file_upload_svc.delete_chat_file(chat_file)


@router.post("/cleanup-orphans")
async def cleanup_orphan_files(
    file_upload_svc: FileUploadSvc,
    _: CurrentAdmin,
    older_than_hours: int = Query(default=24, ge=1, le=24 * 365),
) -> dict[str, int]:
    """Remove old R2 objects not referenced by database metadata."""
    storage = get_file_storage()
    try:
        deleted = await file_upload_svc.cleanup_orphaned_files(storage, older_than_hours)
    except NotImplementedError:
        raise HTTPException(status_code=400, detail="Orphan cleanup requires R2 storage") from None
    return {"deleted": deleted}


@router.get("/{file_id}/info", response_model=FileInfo)
async def get_file_info(
    file_id: UUID,
    file_upload_svc: FileUploadSvc,
    current_user: CurrentUser,
) -> Any:
    """Get file metadata. Only the owner can access."""
    try:
        chat_file = await file_upload_svc.get_user_file(file_id, current_user.id)
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
        ) from None

    return FileInfo(
        id=chat_file.id,
        filename=chat_file.filename,
        mime_type=chat_file.mime_type,
        size=chat_file.size,
        file_type=chat_file.file_type,
        created_at=chat_file.created_at,
        user_id=chat_file.user_id,
    )


def file_upload_allowed_types() -> set[str]:
    """Return allowed upload MIME types without duplicating the storage list."""
    return ALLOWED_MIME_TYPES
