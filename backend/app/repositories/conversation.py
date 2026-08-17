"""Conversation and message data access."""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation, Message


async def list_for_user(
    db: AsyncSession, user_id: UUID, *, skip: int, limit: int, include_archived: bool
) -> tuple[list[Conversation], int]:
    query = select(Conversation).where(Conversation.user_id == user_id)
    count_query = select(Conversation.id).where(Conversation.user_id == user_id)
    if not include_archived:
        query = query.where(Conversation.is_archived.is_(False))
        count_query = count_query.where(Conversation.is_archived.is_(False))
    query = query.order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
    rows = list((await db.execute(query.offset(skip).limit(limit))).scalars().all())
    total = len((await db.execute(count_query)).all())
    return rows, total


async def get_owned(db: AsyncSession, conversation_id: UUID, user_id: UUID) -> Conversation | None:
    return (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id
            )
        )
    ).scalar_one_or_none()


async def create(db: AsyncSession, user_id: UUID, title: str | None) -> Conversation:
    conversation = Conversation(user_id=user_id, title=title)
    db.add(conversation)
    await db.flush()
    await db.refresh(conversation)
    return conversation


async def list_messages(db: AsyncSession, conversation_id: UUID) -> Sequence[Message]:
    return (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
    ).scalars().all()


async def create_message(
    db: AsyncSession,
    conversation_id: UUID,
    role: str,
    content: str,
    model_name: str | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        model_name=model_name,
    )
    db.add(message)
    await db.flush()
    await db.refresh(message)
    return message


async def touch(db: AsyncSession, conversation: Conversation) -> None:
    """Move a conversation to the top of history after a new turn."""
    conversation.updated_at = datetime.now(UTC)
    await db.flush()


async def delete(db: AsyncSession, conversation: Conversation) -> None:
    await db.execute(sql_delete(Conversation).where(Conversation.id == conversation.id))
    await db.flush()
