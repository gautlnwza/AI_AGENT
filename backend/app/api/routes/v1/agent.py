"""WebSocket endpoint for the conversational AI agent."""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic_ai.messages import BinaryContent

from app.agents.assistant import Deps, get_agent
from app.core.config import settings
from app.db.session import get_db_context
from app.repositories import chat_file as chat_file_repo
from app.services.file_storage import get_file_storage

logger = logging.getLogger(__name__)

router = APIRouter()


async def send_event(websocket: WebSocket, event_type: str, data: dict[str, Any]) -> None:
    """Send one frontend-compatible agent event."""
    await websocket.send_json({"type": event_type, "data": data})


async def build_multimodal_input(message: str, file_ids: list[Any]) -> str | list[Any]:
    """Load attached images/text and build a Gemini multimodal prompt."""
    if not file_ids:
        return message

    valid_ids: list[UUID] = []
    for file_id in file_ids:
        try:
            valid_ids.append(UUID(str(file_id)))
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid attached file id: %s", file_id)

    if not valid_ids:
        return message

    storage = get_file_storage()
    image_parts: list[BinaryContent] = []
    text_parts: list[str] = []
    async with get_db_context() as db:
        attached_files = await chat_file_repo.get_many(db, valid_ids)
        for chat_file in attached_files:
            try:
                if chat_file.file_type == "image" or chat_file.mime_type.startswith("image/"):
                    data = await storage.load(chat_file.storage_path)
                    image_parts.append(
                        BinaryContent(data=data, media_type=chat_file.mime_type)
                    )
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
async def agent_websocket(websocket: WebSocket) -> None:
    """Run one AI turn per WebSocket message.

    Conversation persistence is deliberately kept out of the transport path so
    an unavailable optional conversation module cannot make the chat socket
    appear offline. The client receives the standard streaming event sequence.
    """
    await websocket.accept()
    history: list[dict[str, str]] = []

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

            await send_event(websocket, "model_request_start", {})
            try:
                assistant = get_agent(
                    model_name=payload.get("model"),
                    thinking_effort=payload.get("thinking_effort"),
                    temperature=payload.get("temperature"),
                )
                output, _, _ = await assistant.run(
                    await build_multimodal_input(message, file_ids),
                    history=history,
                    deps=Deps(),
                )
                history.extend(
                    [
                        {"role": "user", "content": message},
                        {"role": "assistant", "content": output},
                    ]
                )
                await send_event(websocket, "text_delta", {"index": 0, "content": output})
                await send_event(websocket, "final_result", {"output": output})
            except Exception:
                logger.exception("agent_turn_failed")
                error_message = (
                    "GOOGLE_API_KEY is not configured. Add it to backend/.env and restart the backend."
                    if not settings.GOOGLE_API_KEY
                    else "The AI agent could not complete this request."
                )
                await send_event(
                    websocket,
                    "error",
                    {"message": error_message},
                )
            finally:
                await send_event(websocket, "complete", {})
    except WebSocketDisconnect:
        logger.info("agent_websocket_disconnected")
