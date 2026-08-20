import asyncio
from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    """Keeps all active sockets; broadcasts to every client per installation."""

    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def register(self, installation_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections[installation_id].add(websocket)

    async def disconnect(self, installation_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            sockets = self._connections.get(installation_id)
            if sockets is None:
                return
            sockets.discard(websocket)
            if not sockets:
                self._connections.pop(installation_id, None)

    async def send(self, installation_id: int, message: dict) -> int:
        async with self._lock:
            sockets = tuple(self._connections.get(installation_id, ()))
        delivered = 0
        failed: list[WebSocket] = []
        for socket in sockets:
            try:
                await socket.send_json(message)
                delivered += 1
            except Exception:
                failed.append(socket)
        for socket in failed:
            await self.disconnect(installation_id, socket)
        return delivered

    async def connection_count(self, installation_id: int) -> int:
        async with self._lock:
            return len(self._connections.get(installation_id, ()))

