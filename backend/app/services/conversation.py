"""Conversation business logic."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.repositories import chat_file as chat_file_repo
from app.repositories import conversation as conversation_repo
from app.schemas.conversation import ConversationCreate, ConversationUpdate


class ConversationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_for_user(self, user_id: UUID, *, skip: int, limit: int, include_archived: bool):
        return await conversation_repo.list_for_user(
            self.db, user_id, skip=skip, limit=limit, include_archived=include_archived
        )

    async def get_owned(self, conversation_id: UUID, user_id: UUID):
        conversation = await conversation_repo.get_owned(self.db, conversation_id, user_id)
        if not conversation:
            raise NotFoundError(message="Conversation not found")
        return conversation

    async def create(self, user_id: UUID, data: ConversationCreate):
        return await conversation_repo.create(self.db, user_id, data.title)

    async def update(self, conversation_id: UUID, user_id: UUID, data: ConversationUpdate):
        conversation = await self.get_owned(conversation_id, user_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(conversation, field, value)
        await self.db.flush()
        await self.db.refresh(conversation)
        return conversation

    async def delete(self, conversation_id: UUID, user_id: UUID) -> None:
        conversation = await self.get_owned(conversation_id, user_id)
        await conversation_repo.delete(self.db, conversation)

    async def messages(self, conversation_id: UUID, user_id: UUID):
        await self.get_owned(conversation_id, user_id)
        messages = list(await conversation_repo.list_messages(self.db, conversation_id))
        files = await chat_file_repo.list_for_messages(
            self.db, [message.id for message in messages]
        )
        files_by_message: dict[UUID, list[dict[str, object]]] = {}
        for chat_file in files:
            if chat_file.message_id is None:
                continue
            files_by_message.setdefault(chat_file.message_id, []).append(
                {
                    "id": chat_file.id,
                    "filename": chat_file.filename,
                    "mime_type": chat_file.mime_type,
                    "file_type": chat_file.file_type,
                }
            )
        return [
            {
                "id": message.id,
                "conversation_id": message.conversation_id,
                "role": message.role,
                "content": message.content,
                "model_name": message.model_name,
                "created_at": message.created_at,
                "updated_at": message.updated_at,
                "files": files_by_message.get(message.id, []),
            }
            for message in messages
        ]

    async def message_history(self, conversation_id: UUID, user_id: UUID):
        """Return persisted messages after verifying ownership."""
        await self.get_owned(conversation_id, user_id)
        return await conversation_repo.list_messages(self.db, conversation_id)

    async def add_message(
        self,
        conversation_id: UUID,
        user_id: UUID,
        *,
        role: str,
        content: str,
        model_name: str | None = None,
    ):
        conversation = await self.get_owned(conversation_id, user_id)
        message = await conversation_repo.create_message(
            self.db,
            conversation_id,
            role,
            content,
            model_name,
        )
        await conversation_repo.touch(self.db, conversation)
        return message
