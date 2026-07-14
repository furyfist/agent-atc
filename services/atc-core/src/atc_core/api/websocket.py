"""WebSocket endpoint: broadcasts EventBus events to connected clients.
See PROJECT_PLAN.md S8: action.pending, action.resolved, agent.heartbeat,
risk.updated.
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    event_bus = websocket.app.state.event_bus
    await websocket.accept()
    queue = event_bus.subscribe()
    try:
        while True:
            event = await queue.get()
            await websocket.send_json({"type": event.type, "payload": event.payload})
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(queue)
