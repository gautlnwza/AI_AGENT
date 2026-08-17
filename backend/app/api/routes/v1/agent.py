"""WebSocket endpoint for the conversational AI agent."""

import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic_ai.messages import BinaryContent

from app.agents.assistant import Deps, get_agent
from app.api.deps import get_current_user_ws
from app.core.config import settings
from app.db.models.user import User
from app.db.session import get_db_context
from app.repositories import chat_file as chat_file_repo
from app.schemas.conversation import ConversationCreate
from app.services.conversation import ConversationService
from app.services.file_storage import get_file_storage

logger = logging.getLogger(__name__)

router = APIRouter()


async def send_event(websocket: WebSocket, event_type: str, data: dict[str, Any]) -> None:
    """Send one frontend-compatible agent event."""
    await websocket.send_json({"type": event_type, "data": data})


async def build_multimodal_input(message: str, attached_files: list[Any]) -> str | list[Any]:
    """Load attached images/text and build a Gemini multimodal prompt."""
    if not attached_files:
        return message

    storage = get_file_storage()
    image_parts: list[BinaryContent] = []
    text_parts: list[str] = []
    for chat_file in attached_files:
        try:
            if chat_file.file_type == "image" or chat_file.mime_type.startswith("image/"):
                data = await storage.load(chat_file.storage_path)
                image_parts.append(BinaryContent(data=data, media_type=chat_file.mime_type))
            elif chat_file.parsed_content:
                text_parts.append(
                    f"\n---\nAttached file: {chat_file.filename}\n"
                    f"```\n{chat_file.parsed_content}\n```"
                )
        except Exception:
            logger.exception("Failed to load attached file %s", chat_file.id)

    full_message = message + "".join(text_parts)
    return [full_message, *image_parts] if image_parts else full_message


@router.get("/agent/models")
async def list_models() -> dict[str, Any]:
    """Return available LLM models and the configured default."""
    return {"default": settings.AI_MODEL, "models": settings.AI_AVAILABLE_MODELS}


@router.websocket("/ws/agent")
async def agent_websocket(
    websocket: WebSocket,
    current_user: Annotated[User, Depends(get_current_user_ws)],
) -> None:
    """Run authenticated AI turns and persist their conversation history."""
    await websocket.accept(subprotocol=getattr(websocket.state, "accept_subprotocol", None))

    try:
        while True:
            payload = await websocket.receive_json()
            message = payload.get("message")
            file_ids = payload.get("file_ids") or []
            if not isinstance(message, str):
                message = ""
            if not message.strip() and not file_ids:
                await send_event(websocket, "error", {"message": "Empty message"})
                continue

            conversation_id: UUID | None = None
            try:
                valid_file_ids = [UUID(str(file_id)) for file_id in file_ids]
                requested_id = payload.get("conversation_id")

                async with get_db_context() as db:
                    service = ConversationService(db)
                    is_new = not requested_id
                    if requested_id:
                        conversation_id = UUID(str(requested_id))
                        await service.get_owned(conversation_id, current_user.id)
                    else:
                        conversation = await service.create(
                            current_user.id,
                            ConversationCreate(title=message.strip()[:50] or "New conversation"),
                        )
                        conversation_id = conversation.id

                    history_messages = await service.message_history(
                        conversation_id, current_user.id
                    )
                    history = [
                        {"role": item.role, "content": item.content}
                        for item in history_messages
                        if item.role in {"user", "assistant", "system"}
                    ]

                    attached_files = await chat_file_repo.get_many_owned(
                        db, valid_file_ids, current_user.id
                    )
                    if len(attached_files) != len(set(valid_file_ids)):
                        raise ValueError("One or more attachments are invalid")
                    if any(chat_file.message_id is not None for chat_file in attached_files):
                        raise ValueError("One or more attachments are already linked")

                    user_message = await service.add_message(
                        conversation_id,
                        current_user.id,
                        role="user",
                        content=message,
                    )
                    await chat_file_repo.link_to_message(
                        db, message_id=user_message.id, file_ids=valid_file_ids
                    )

                if is_new:
                    await send_event(
                        websocket,
                        "conversation_created",
                        {"conversation_id": str(conversation_id)},
                    )

                await send_event(websocket, "model_request_start", {})
                assistant = get_agent(
                    model_name=payload.get("model"),
                    thinking_effort=payload.get("thinking_effort"),
                    temperature=payload.get("temperature"),
                )
                output, _, _ = await assistant.run(
                    await build_multimodal_input(message, attached_files),
                    history=history,
                    deps=Deps(user_id=str(current_user.id)),
                )

                async with get_db_context() as db:
                    service = ConversationService(db)
                    assistant_message = await service.add_message(
                        conversation_id,
                        current_user.id,
                        role="assistant",
                        content=output,
                        model_name=assistant.model_name,
                    )

                await send_event(websocket, "text_delta", {"index": 0, "content": output})
                await send_event(websocket, "final_result", {"output": output})
                await send_event(
                    websocket,
                    "message_saved",
                    {
                        "message_id": str(assistant_message.id),
                        "conversation_id": str(conversation_id),
                    },
                )
            except (TypeError, ValueError):
                logger.exception("invalid_chat_request")
                await send_event(websocket, "error", {"message": "Invalid conversation or file"})
            except Exception:
                logger.exception("agent_turn_failed")
                error_message = (
                    "GOOGLE_API_KEY is not configured. Add it to backend/.env "
                    "and restart the backend."
                    if not settings.GOOGLE_API_KEY
                    else "The AI agent could not complete this request."
                )
                await send_event(
                    websocket,
                    "error",
                    {"message": error_message},
                )
            finally:
                await send_event(
                    websocket,
                    "complete",
                    {"conversation_id": str(conversation_id) if conversation_id else None},
                )
    except WebSocketDisconnect:
        logger.info("agent_websocket_disconnected")
