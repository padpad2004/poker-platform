import json
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import jwt

from . import models
from .tables_api import (
    TABLE_CONNECTIONS,
    USER_CONNECTIONS,
    broadcast_table_state,
    _get_engine_table,
)
from .deps import SECRET_KEY, ALGORITHM
from .database import SessionLocal

ws_router = APIRouter()
TABLE_CHAT_LOGS: Dict[int, List[dict]] = {}


def _get_user_id_from_token(token: Optional[str]) -> Optional[int]:
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        return int(sub) if sub is not None else None
    except Exception:
        return None


def _resolve_username(user_id: Optional[int], fallback: Optional[str] = None) -> str:
    if user_id is None:
        return fallback or "Spectator"

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if user and user.username:
            return user.username
    finally:
        db.close()

    return fallback or "Player"


def _append_chat_message(table_id: int, message: dict) -> None:
    history = TABLE_CHAT_LOGS.setdefault(table_id, [])
    history.append(message)
    if len(history) > 50:
        del history[:-50]


async def _broadcast_chat(table_id: int, payload: dict) -> None:
    connections = TABLE_CONNECTIONS.get(table_id, {})
    for ws in list(connections.keys()):
        try:
            await ws.send_json(payload)
        except Exception:
            connections.pop(ws, None)


@ws_router.websocket("/ws/tables/{table_id}")
async def table_ws(websocket: WebSocket, table_id: int):
    # Accept the connection
    await websocket.accept()

    # Ensure engine table exists
    db = SessionLocal()
    try:
        _get_engine_table(table_id, db)
    except Exception:
        await websocket.close()
        db.close()
        return
    finally:
        db.close()

    # Get token from query string: ws://.../ws/tables/1?token=...
    token = websocket.query_params.get("token")
    viewer_user_id = _get_user_id_from_token(token)

    if table_id not in TABLE_CONNECTIONS:
        TABLE_CONNECTIONS[table_id] = {}
    TABLE_CONNECTIONS[table_id][websocket] = viewer_user_id

    if viewer_user_id is not None:
        USER_CONNECTIONS.setdefault(viewer_user_id, set()).add(websocket)

    # Send initial state + chat backlog
    await websocket.send_json({"type": "chat_history", "messages": TABLE_CHAT_LOGS.get(table_id, [])})
    await broadcast_table_state(table_id)

    try:
        while True:
            # We don't care what the client sends; just keep the connection alive
            raw_message = await websocket.receive_text()
            try:
                payload = json.loads(raw_message)
            except Exception:
                payload = None

            if isinstance(payload, dict) and payload.get("type") == "chat_message":
                message_text = str(payload.get("message") or "").strip()
                if not message_text:
                    continue
                username = _resolve_username(
                    viewer_user_id, str(payload.get("username") or "").strip()
                )
                entry = {
                    "id": f"{table_id}-{int(datetime.utcnow().timestamp() * 1000)}",
                    "user_id": viewer_user_id,
                    "username": username,
                    "message": message_text,
                    "timestamp": datetime.utcnow().isoformat(),
                }
                _append_chat_message(table_id, entry)
                await _broadcast_chat(table_id, {"type": "chat_message", "message": entry})
                continue

            await broadcast_table_state(table_id)
    except WebSocketDisconnect:
        pass
    finally:
        TABLE_CONNECTIONS.get(table_id, {}).pop(websocket, None)
        if table_id in TABLE_CONNECTIONS and not TABLE_CONNECTIONS[table_id]:
            del TABLE_CONNECTIONS[table_id]

        if viewer_user_id is not None:
            sockets = USER_CONNECTIONS.get(viewer_user_id)
            if sockets is not None:
                sockets.discard(websocket)
                if not sockets:
                    del USER_CONNECTIONS[viewer_user_id]
