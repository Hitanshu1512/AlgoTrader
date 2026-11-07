"""WebSocket auth tests. Uses Starlette's TestClient so the app runs its own lifespan."""

import pyotp
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from tests.conftest import ORIGIN, OWNER_EMAIL, OWNER_PASSWORD, make_settings


def _enrolled_client(client: TestClient) -> None:
    r = client.post("/api/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
    assert r.status_code == 200, r.text
    csrf = {"X-CSRF-Token": client.cookies.get("at_csrf") or ""}
    secret = client.post("/api/auth/mfa/enroll/start", headers=csrf).json()["secret"]
    r = client.post(
        "/api/auth/mfa/enroll/confirm", json={"code": pyotp.TOTP(secret).now()}, headers=csrf
    )
    assert r.status_code == 200, r.text


@pytest.fixture
def ws_client(ctx: object) -> TestClient:  # ctx fixture cleans DB/Redis first
    import asyncio

    from app.main import build_context

    settings = make_settings()

    async def owner() -> None:
        c = build_context(settings)
        async with c.sessionmaker() as db:
            await c.auth.create_owner(db, OWNER_EMAIL, OWNER_PASSWORD)
            await db.commit()
        await c.redis.aclose()
        await c.engine.dispose()

    asyncio.run(owner())
    return TestClient(create_app(settings), base_url=ORIGIN)


def test_ws_rejects_unauthenticated(ws_client: TestClient) -> None:
    with (
        ws_client,
        pytest.raises(WebSocketDisconnect) as exc,
        ws_client.websocket_connect("/api/ws", headers={"origin": ORIGIN}),
    ):
        pass
    assert exc.value.code == 1008


def test_ws_rejects_foreign_origin(ws_client: TestClient) -> None:
    with ws_client:
        _enrolled_client(ws_client)
        with (
            pytest.raises(WebSocketDisconnect) as exc,
            ws_client.websocket_connect("/api/ws", headers={"origin": "https://evil.example"}),
        ):
            pass
    assert exc.value.code == 1008


def test_ws_streams_status_when_authenticated(ws_client: TestClient) -> None:
    with ws_client:
        _enrolled_client(ws_client)
        with ws_client.websocket_connect("/api/ws", headers={"origin": ORIGIN}) as ws:
            assert ws.receive_json()["topic"] == "hello"
            msg = ws.receive_json()
            assert msg["topic"] == "system.status"
            assert {c["name"] for c in msg["data"]["components"]} >= {"database", "redis"}
