"""Conversation API schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class ConversationCreate(BaseSchema):
    title: str | None = Field(default=None, max_length=255)


class ConversationUpdate(BaseSchema):
    title: str | None = Field(default=None, max_length=255)
    is_archived: bool | None = None


class ConversationRead(BaseSchema):
    id: UUID
    user_id: UUID | None
    title: str | None
    is_archived: bool
    created_at: datetime
    updated_at: datetime | None


class ConversationList(BaseSchema):
    items: list[ConversationRead]
    total: int


class MessageFileRead(BaseSchema):
    id: UUID
    filename: str
    mime_type: str
    file_type: str


class MessageRead(BaseSchema):
    id: UUID
    conversation_id: UUID
    role: str
    content: str
    model_name: str | None
    created_at: datetime
    updated_at: datetime | None
    files: list[MessageFileRead] = Field(default_factory=list)


class MessageList(BaseSchema):
    items: list[MessageRead]
    total: int
