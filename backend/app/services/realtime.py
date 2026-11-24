from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Set

from fastapi import WebSocket


@dataclass(eq=False)
class ClientConn:
    websocket: WebSocket
    user_id: int
    role: str
    session_token: str


class RealtimeHub:
    """
    Authenticated WebSocket hub with strict per-user isolation:
    - Public/global market & signal events broadcast to authenticated clients.
    - Private notifications & account events ONLY routed to matching `user_id`.
    - Enforces max concurrent connections per user.
    """

    MAX_CONNS_PER_USER = 5

    def __init__(self) -> None:
        self._by_user: Dict[int, Set[ClientConn]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, user_id: int, role: str, session_token: str) -> ClientConn:
        await ws.accept()
        conn = ClientConn(websocket=ws, user_id=user_id, role=role, session_token=session_token)
        async with self._lock:
            user_set = self._by_user[user_id]
            if len(user_set) >= self.MAX_CONNS_PER_USER:
                oldest = next(iter(user_set))
                user_set.discard(oldest)
                try:
                    await oldest.websocket.close(code=4008, reason="Connection limit exceeded")
                except Exception:
                    pass
            user_set.add(conn)
        return conn

    async def disconnect(self, conn: ClientConn) -> None:
        async with self._lock:
            if conn.user_id in self._by_user:
                self._by_user[conn.user_id].discard(conn)
                if not self._by_user[conn.user_id]:
                    del self._by_user[conn.user_id]

    async def disconnect_session(self, user_id: int, session_token: str) -> None:
        async with self._lock:
            conns = list(self._by_user.get(user_id, set()))
        for c in conns:
            if c.session_token == session_token:
                try:
                    await c.websocket.close(code=4001, reason="Session revoked")
                except Exception:
                    pass
                await self.disconnect(c)

    async def broadcast_public(self, event_type: str, payload: dict) -> None:
        msg = json.dumps({"type": event_type, "data": payload}, default=str, ensure_ascii=False)
        async with self._lock:
            all_conns = [c for s in self._by_user.values() for c in s]
        for c in all_conns:
            try:
                await c.websocket.send_text(msg)
            except Exception:
                await self.disconnect(c)

    async def send_to_user(self, user_id: int, event_type: str, payload: dict) -> None:
        msg = json.dumps({"type": event_type, "data": payload}, default=str, ensure_ascii=False)
        async with self._lock:
            conns = list(self._by_user.get(user_id, set()))
        for c in conns:
            try:
                await c.websocket.send_text(msg)
            except Exception:
                await self.disconnect(c)


realtime_hub = RealtimeHub()
