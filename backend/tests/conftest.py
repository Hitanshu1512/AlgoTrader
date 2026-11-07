"""Test fixtures.

Integration tests use a real PostgreSQL and Redis (CI provides them as services):
  ALGOTRADER_TEST_DATABASE_URL  (default postgresql+asyncpg://algotrader:algotrader@localhost:5432/algotrader_test)
  ALGOTRADER_TEST_REDIS_URL     (default redis://localhost:6379/15)
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pyotp
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text

from app.api.deps import AppContext
from app.core.config import AppEnv, Settings
from app.main import build_context, create_app

TEST_DB = os.environ.get(
    "ALGOTRADER_TEST_DATABASE_URL",
    "postgresql+asyncpg://algotrader:algotrader@localhost:5432/algotrader_test",
)
TEST_REDIS = os.environ.get("ALGOTRADER_TEST_REDIS_URL", "redis://localhost:6379/15")
ORIGIN = "http://testserver"
OWNER_EMAIL = "owner@example.com"
OWNER_PASSWORD = "Correct-Horse-42-battery"


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": AppEnv.TEST,
        "database_url": TEST_DB,
        "redis_url": TEST_REDIS,
        "cookie_secure": False,
        "public_origin": ORIGIN,
        "log_json": False,
        "log_level": "WARNING",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture(scope="session")
def migrated_db() -> None:
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    async def reset() -> None:
        engine = create_async_engine(TEST_DB)
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        await engine.dispose()

    asyncio.run(reset())
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option(
        "script_location", os.path.join(os.path.dirname(__file__), "..", "migrations")
    )
    cfg.attributes["database_url"] = TEST_DB
    command.upgrade(cfg, "head")


async def _clean(ctx: AppContext) -> None:
    async with ctx.engine.begin() as conn:
        await conn.execute(text("ALTER TABLE audit_logs DISABLE TRIGGER USER"))
        await conn.execute(
            text(
                "TRUNCATE audit_logs, system_events, user_sessions, users RESTART IDENTITY CASCADE"
            )
        )
        await conn.execute(text("ALTER TABLE audit_logs ENABLE TRIGGER USER"))
    await ctx.redis.flushdb()


@pytest.fixture
async def ctx(migrated_db: None) -> AsyncIterator[AppContext]:
    context = build_context(
        make_settings(), redis=Redis.from_url(TEST_REDIS, decode_responses=True)
    )
    await _clean(context)
    yield context
    await context.redis.aclose()
    await context.engine.dispose()


@pytest.fixture
async def client(ctx: AppContext) -> AsyncIterator[AsyncClient]:
    app = create_app(ctx.settings, context=ctx)
    app.state.ctx = ctx
    async with AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN) as c:
        yield c


class FakeClock:
    """Controls the time seen by TOTP verification so codes from distinct steps can be used."""

    def __init__(self) -> None:
        self.now = time.time()

    def time(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeClock]:
    fake = FakeClock()
    import app.core.security as security

    monkeypatch.setattr(security.time, "time", fake.time)
    yield fake


def totp_now(secret: str, clock: FakeClock) -> str:
    return pyotp.TOTP(secret).at(clock.now)


async def create_owner(ctx: AppContext) -> None:
    async with ctx.sessionmaker() as db:
        await ctx.auth.create_owner(db, OWNER_EMAIL, OWNER_PASSWORD)
        await db.commit()


def csrf_headers(client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("at_csrf") or ""}


async def login_and_enroll(client: AsyncClient, ctx: AppContext, clock: FakeClock) -> str:
    """Create owner, log in, enrol MFA. Returns the TOTP secret."""
    await create_owner(ctx)
    r = await client.post(
        "/api/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}
    )
    assert r.status_code == 200, r.text
    r = await client.post("/api/auth/mfa/enroll/start", headers=csrf_headers(client))
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    r = await client.post(
        "/api/auth/mfa/enroll/confirm",
        json={"code": totp_now(secret, clock)},
        headers=csrf_headers(client),
    )
    assert r.status_code == 200, r.text
    clock.advance(30)
    return str(secret)
