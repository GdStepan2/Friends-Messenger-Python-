import json
import asyncio
from typing import Optional

from PySide6.QtCore import QThread, Signal
import websockets


class WsWorker(QThread):
    connected = Signal()
    login_ok = Signal(bool)                 # is_admin
    login_error = Signal(str)

    message_received = Signal(dict)
    history_received = Signal(list)         # messages
    presence_received = Signal(list)        # online usernames

    admin_create_user_ok = Signal(str)
    admin_create_user_error = Signal(str)

    disconnected = Signal(str)
    error = Signal(str)

    def __init__(self, host: str, port: int, username: str, password: str):
        super().__init__()
        self.host = host
        self.port = port
        self.username = username
        self.password = password

        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.cmd_q: Optional[asyncio.Queue] = None

    def submit(self, msg: dict):
        if self.loop and self.cmd_q and not self.loop.is_closed():
            try:
                self.loop.call_soon_threadsafe(self.cmd_q.put_nowait, msg)
            except Exception:
                pass

    def stop(self):
        if self.loop and self.cmd_q and not self.loop.is_closed():
            try:
                self.loop.call_soon_threadsafe(self.cmd_q.put_nowait, {"type": "_stop"})
            except Exception:
                pass

    def run(self):
        asyncio.run(self._main())

    async def _main(self):
        self.loop = asyncio.get_running_loop()
        self.cmd_q = asyncio.Queue()

        uri = f"ws://{self.host}:{self.port}"

        try:
            async with websockets.connect(uri, max_size=2_000_000) as ws:
                self.connected.emit()

                await ws.send(json.dumps({
                    "type": "login",
                    "username": self.username,
                    "password": self.password
                }, ensure_ascii=False))

                first = await ws.recv()
                try:
                    obj = json.loads(first)
                except Exception:
                    self.login_error.emit("Bad server response")
                    return

                if obj.get("type") == "login_error":
                    self.login_error.emit(obj.get("message", "Login failed"))
                    return

                if obj.get("type") != "login_ok":
                    self.login_error.emit("Unexpected server response")
                    return

                is_admin = bool(obj.get("is_admin", False))
                self.login_ok.emit(is_admin)

                async def receiver():
                    try:
                        async for raw in ws:
                            try:
                                msg = json.loads(raw)
                            except Exception:
                                continue

                            t = msg.get("type")
                            if t == "message":
                                self.message_received.emit(msg.get("message", {}))
                            elif t == "history":
                                self.history_received.emit(msg.get("messages", []))
                            elif t == "presence":
                                self.presence_received.emit(msg.get("online", []))
                            elif t == "admin_create_user_ok":
                                self.admin_create_user_ok.emit(msg.get("username", ""))
                            elif t == "admin_create_user_error":
                                self.admin_create_user_error.emit(msg.get("message", ""))
                            elif t == "error":
                                self.error.emit(msg.get("message", "Unknown error"))
                    except Exception as e:
                        self.disconnected.emit(str(e))

                async def sender():
                    while True:
                        cmd = await self.cmd_q.get()
                        if cmd.get("type") == "_stop":
                            break
                        try:
                            await ws.send(json.dumps(cmd, ensure_ascii=False))
                        except Exception as e:
                            self.disconnected.emit(str(e))
                            break

                recv_task = asyncio.create_task(receiver())
                send_task = asyncio.create_task(sender())
                done, pending = await asyncio.wait({recv_task, send_task}, return_when=asyncio.FIRST_COMPLETED)
                for p in pending:
                    p.cancel()

        except Exception as e:
            self.login_error.emit(f"Connection failed: {e}")
        finally:
            self.disconnected.emit("Disconnected")
