import asyncio
import json
from typing import Dict, Any, Set

import websockets
from websockets.server import WebSocketServerProtocol
from websockets.exceptions import ConnectionClosed

from db import (
    get_engine,
    ensure_schema,
    authenticate,
    create_user,
    insert_message,
    fetch_history,
)

SESSIONS: Dict[WebSocketServerProtocol, Dict[str, Any]] = {}
CONNS: Set[WebSocketServerProtocol] = set()


def jdump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


async def send_json(ws: WebSocketServerProtocol, obj: Any) -> None:
    await ws.send(jdump(obj))


def online_usernames() -> list[str]:
    names = []
    for ws, s in SESSIONS.items():
        if s.get("authed") and s.get("username"):
            names.append(s["username"])
    names = sorted(set(names), key=lambda x: x.lower())
    return names


async def broadcast(obj: Any) -> None:
    payload = jdump(obj)
    dead = []
    for w in list(CONNS):
        try:
            await w.send(payload)
        except Exception:
            dead.append(w)
    for w in dead:
        await cleanup_ws(w)


async def broadcast_presence() -> None:
    await broadcast({"type": "presence", "online": online_usernames()})


async def cleanup_ws(ws: WebSocketServerProtocol) -> None:
    CONNS.discard(ws)
    SESSIONS.pop(ws, None)
    await broadcast_presence()


def require_authed(ws: WebSocketServerProtocol) -> Dict[str, Any]:
    sess = SESSIONS.get(ws)
    if not sess or not sess.get("authed"):
        raise PermissionError("Not authenticated")
    return sess


async def handler(ws: WebSocketServerProtocol, engine) -> None:
    CONNS.add(ws)
    SESSIONS[ws] = {"authed": False}

    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception:
                await send_json(ws, {"type": "error", "message": "Invalid JSON"})
                continue

            mtype = msg.get("type")

            # LOGIN
            if mtype == "login":
                username = (msg.get("username") or "").strip()
                password = msg.get("password") or ""
                u = authenticate(engine, username, password)
                if not u:
                    await send_json(ws, {"type": "login_error", "message": "Invalid credentials or inactive user"})
                    continue

                SESSIONS[ws] = {
                    "authed": True,
                    "user_id": int(u["id"]),
                    "username": u["username"],
                    "is_admin": bool(u["is_admin"]),
                }

                await send_json(ws, {
                    "type": "login_ok",
                    "username": u["username"],
                    "is_admin": bool(u["is_admin"]),
                })

                # history (single chat)
                hist = fetch_history(engine, limit=80)
                await send_json(ws, {"type": "history", "messages": hist})

                # presence
                await broadcast_presence()
                continue

            # below requires auth
            try:
                sess = require_authed(ws)
            except PermissionError:
                await send_json(ws, {"type": "error", "message": "Please login first"})
                continue

            # SEND message (text/sticker + reply)
            if mtype == "send":
                kind = (msg.get("kind") or "text").strip().lower()
                content = msg.get("content") or ""
                sticker = msg.get("sticker")
                reply_to = msg.get("reply_to")

                try:
                    base = insert_message(
                        engine,
                        user_id=sess["user_id"],
                        content=content,
                        kind=kind,
                        sticker=sticker,
                        reply_to=int(reply_to) if reply_to is not None else None
                    )
                except Exception as e:
                    await send_json(ws, {"type": "error", "message": f"Send failed: {e}"})
                    continue

                full = {
                    "id": base["id"],
                    "user_id": sess["user_id"],
                    "username": sess["username"],
                    "kind": base.get("kind", "text"),
                    "sticker": base.get("sticker"),
                    "reply_to": base.get("reply_to"),
                    "content": base.get("content", ""),
                    "created_at": base["created_at"],
                }

                await broadcast({"type": "message", "message": full})
                continue

            # WHO ONLINE (optional request)
            if mtype == "who_online":
                await send_json(ws, {"type": "presence", "online": online_usernames()})
                continue

            # ADMIN: CREATE USER
            if mtype == "admin_create_user":
                if not sess.get("is_admin"):
                    await send_json(ws, {"type": "admin_create_user_error", "message": "Admin only"})
                    continue

                new_username = (msg.get("username") or "").strip()
                new_password = msg.get("password") or ""
                new_is_admin = bool(msg.get("is_admin", False))

                try:
                    create_user(engine, new_username, new_password, is_admin=new_is_admin, is_active=True)
                    await send_json(ws, {"type": "admin_create_user_ok", "username": new_username})
                except Exception as e:
                    await send_json(ws, {"type": "admin_create_user_error", "message": str(e)})
                continue

            # rooms disabled
            if mtype in ("join", "history_room"):
                await send_json(ws, {"type": "error", "message": "Rooms are disabled. Single chat only."})
                continue

            await send_json(ws, {"type": "error", "message": f"Unknown type: {mtype}"})

    except ConnectionClosed:
        pass
    finally:
        await cleanup_ws(ws)


async def run_server(host: str, port: int) -> None:
    engine = get_engine()
    ensure_schema(engine)

    async def _handler(*args):
        ws = args[0]  # new websockets: (connection,), old: (ws, path)
        await handler(ws, engine)

    print(f"Server listening on ws://{host}:{port}")
    async with websockets.serve(_handler, host, port, max_size=2_000_000):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(run_server("0.0.0.0", 8765))
