"""WebSocket endpoint for the conversational AI agent."""

import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.agents.assistant import Deps, get_agent
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


async def send_event(websocket: WebSocket, event_type: str, data: dict[str, Any]) -> None:
    """Send one frontend-compatible agent event."""
    await websocket.send_json({"type": event_type, "data": data})


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
            if not isinstance(message, str) or not message.strip():
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
                    message,
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
                await send_event(
                    websocket,
                    "error",
                    {"message": "The AI agent could not complete this request."},
                )
            finally:
                await send_event(websocket, "complete", {})
    except WebSocketDisconnect:
        logger.info("agent_websocket_disconnected")
