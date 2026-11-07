"""Dashboard WebSocket.

Authenticated with the same httpOnly session cookie as REST; the Origin header must match
the configured public origin (blocks cross-site WebSocket hijacking). The session is
re-validated on every heartbeat, so logout or expiry disconnects the socket.
"""

from __future__ import annotations

import asyncio
import contextlib
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from redis.exceptions import RedisError

from app.api.deps import AppContext, session_cookie_name
from app.api.system import collect_status
from app.core.events import CHANNEL
from app.core.logging import get_logger

router = APIRouter()
log = get_logger(__name__)
HEARTBEAT_SECONDS = 5


async def _session_valid(ctx: AppContext, token: str | None) -> bool:
    async with ctx.sessionmaker() as db:
        sess = await ctx.auth.resolve_session(db, token)
        return sess is not None and sess.mfa_verified_at is not None


@router.websocket("/ws")
async def dashboard_ws(websocket: WebSocket) -> None:
    ctx: AppContext = websocket.app.state.ctx
    origin = websocket.headers.get("origin")
    token = websocket.cookies.get(session_cookie_name(ctx.settings))
    if origin != ctx.settings.public_origin or not await _session_valid(ctx, token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    await websocket.send_json({"topic": "hello", "data": {"heartbeat_seconds": HEARTBEAT_SECONDS}})

    async def heartbeat() -> None:
        while True:
            if not await _session_valid(ctx, token):
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            sys_status = await collect_status(ctx)
            await websocket.send_json({"topic": "system.status", "data": sys_status.model_dump()})
            await asyncio.sleep(HEARTBEAT_SECONDS)

    async def relay() -> None:
        while True:
            pubsub = ctx.redis.pubsub()
            try:
                await pubsub.subscribe(CHANNEL)
                async for message in pubsub.listen():
                    if message.get("type") == "message":
                        await websocket.send_json(json.loads(message["data"]))
            except RedisError:
                log.warning("ws_relay_redis_error_retrying")
                await asyncio.sleep(2)
            finally:
                with contextlib.suppress(Exception):
                    await pubsub.aclose()  # type: ignore[no-untyped-call]

    async def receive() -> None:
        # Client messages are only pings; anything else is ignored (no commands over WS).
        while True:
            await websocket.receive_text()

    tasks = [asyncio.create_task(t()) for t in (heartbeat, relay, receive)]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                log.warning("ws_task_failed", error=type(exc).__name__)
    finally:
        for task in tasks:
            task.cancel()
        with contextlib.suppress(Exception):
            await websocket.close()
