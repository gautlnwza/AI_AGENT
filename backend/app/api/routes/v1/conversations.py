"""Conversation and message endpoints."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import ConversationSvc, CurrentUser
from app.schemas.conversation import (
    ConversationCreate,
    ConversationList,
    ConversationRead,
    ConversationUpdate,
    MessageList,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=ConversationList)
async def list_conversations(
    service: ConversationSvc,
    current_user: CurrentUser,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
    include_archived: bool = False,
) -> dict[str, Any]:
    items, total = await service.list_for_user(
        current_user.id, skip=skip, limit=limit, include_archived=include_archived
    )
    return {"items": items, "total": total}


@router.post("", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate, service: ConversationSvc, current_user: CurrentUser
) -> Any:
    return await service.create(current_user.id, body)


@router.get("/{conversation_id}/messages", response_model=MessageList)
async def list_messages(
    conversation_id: UUID, service: ConversationSvc, current_user: CurrentUser
) -> dict[str, Any]:
    items = await service.messages(conversation_id, current_user.id)
    return {"items": items, "total": len(items)}


@router.patch("/{conversation_id}", response_model=ConversationRead)
async def update_conversation(
    conversation_id: UUID,
    body: ConversationUpdate,
    service: ConversationSvc,
    current_user: CurrentUser,
) -> Any:
    return await service.update(conversation_id, current_user.id, body)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID, service: ConversationSvc, current_user: CurrentUser
) -> None:
    await service.delete(conversation_id, current_user.id)
