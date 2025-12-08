from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import jwt

from .tables_api import TABLE_CONNECTIONS, broadcast_table_state, _get_engine_table
from .deps import SECRET_KEY, ALGORITHM
from .database import SessionLocal

ws_router = APIRouter()


def _get_user_id_from_token(token: Optional[str]) -> Optional[int]:
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        return int(sub) if sub is not None else None
    except Exception:
        return None


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

    # Send initial state
    await broadcast_table_state(table_id)

    try:
        while True:
            # We don't care what the client sends; just keep the connection alive
            await websocket.receive_text()
            await broadcast_table_state(table_id)
    except WebSocketDisconnect:
        TABLE_CONNECTIONS[table_id].pop(websocket, None)
        if not TABLE_CONNECTIONS[table_id]:
            del TABLE_CONNECTIONS[table_id]
