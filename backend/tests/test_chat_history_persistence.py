"""Focused tests for the conversation history persistence contract."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.conversation import ConversationService


@pytest.mark.anyio
async def test_messages_include_attachment_metadata() -> None:
    db = AsyncMock()
    service = ConversationService(db)
    conversation_id = uuid4()
    user_id = uuid4()
    message_id = uuid4()
    message = SimpleNamespace(
        id=message_id,
        conversation_id=conversation_id,
        role="user",
        content="See attachment",
        model_name=None,
        created_at=None,
        updated_at=None,
    )
    chat_file = SimpleNamespace(
        id=uuid4(),
        message_id=message_id,
        filename="notes.txt",
        mime_type="text/plain",
        file_type="text",
    )

    with (
        patch.object(service, "get_owned", AsyncMock()),
        patch(
            "app.services.conversation.conversation_repo.list_messages",
            AsyncMock(return_value=[message]),
        ),
        patch(
            "app.services.conversation.chat_file_repo.list_for_messages",
            AsyncMock(return_value=[chat_file]),
        ),
    ):
        result = await service.messages(conversation_id, user_id)

    assert result[0]["files"] == [
        {
            "id": chat_file.id,
            "filename": "notes.txt",
            "mime_type": "text/plain",
            "file_type": "text",
        }
    ]


@pytest.mark.anyio
async def test_add_message_verifies_owner_and_touches_conversation() -> None:
    db = AsyncMock()
    service = ConversationService(db)
    conversation_id = uuid4()
    user_id = uuid4()
    conversation = SimpleNamespace(id=conversation_id)
    saved_message = SimpleNamespace(id=uuid4())

    with (
        patch.object(service, "get_owned", AsyncMock(return_value=conversation)) as get_owned,
        patch(
            "app.services.conversation.conversation_repo.create_message",
            AsyncMock(return_value=saved_message),
        ) as create_message,
        patch(
            "app.services.conversation.conversation_repo.touch", AsyncMock()
        ) as touch,
    ):
        result = await service.add_message(
            conversation_id,
            user_id,
            role="assistant",
            content="Saved response",
            model_name="test-model",
        )

    assert result is saved_message
    get_owned.assert_awaited_once_with(conversation_id, user_id)
    create_message.assert_awaited_once_with(
        db,
        conversation_id,
        "assistant",
        "Saved response",
        "test-model",
    )
    touch.assert_awaited_once_with(db, conversation)
