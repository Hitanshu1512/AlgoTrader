from __future__ import annotations

import ipaddress
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.auth.service import AuthService
from app.core.config import Settings
from app.core.crypto import EnvelopeCipher
from app.core.events import EventBus
from app.core.security import constant_time_equals
from app.db.models import UserSession


@dataclass
class AppContext:
    settings: Settings
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    redis: Redis
    cipher: EnvelopeCipher
    auth: AuthService
    events: EventBus


def get_ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx


Ctx = Annotated[AppContext, Depends(get_ctx)]


async def get_db(ctx: Ctx) -> AsyncIterator[AsyncSession]:
    async with ctx.sessionmaker() as session:
        yield session


DB = Annotated[AsyncSession, Depends(get_db)]


# ───────────────────────── cookies ─────────────────────────


def session_cookie_name(settings: Settings) -> str:
    # The __Host- prefix forces Secure, Path=/ and no Domain attribute in browsers.
    return "__Host-at_session" if settings.cookie_secure else "at_session"


def csrf_cookie_name(settings: Settings) -> str:
    return "__Host-at_csrf" if settings.cookie_secure else "at_csrf"


CSRF_HEADER = "X-CSRF-Token"


def set_auth_cookies(response: Response, settings: Settings, token: str, max_age: int) -> str:
    csrf = secrets.token_urlsafe(32)
    common = {
        "secure": settings.cookie_secure,
        "samesite": "strict",
        "path": "/",
        "max_age": max_age,
    }
    response.set_cookie(session_cookie_name(settings), token, httponly=True, **common)  # type: ignore[arg-type]
    response.set_cookie(csrf_cookie_name(settings), csrf, httponly=False, **common)  # type: ignore[arg-type]
    return csrf


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    for name in (session_cookie_name(settings), csrf_cookie_name(settings)):
        response.delete_cookie(name, path="/", secure=settings.cookie_secure, samesite="strict")


def client_ip(request: Request) -> str | None:
    """Client address as seen by uvicorn (which trusts X-Forwarded-For only from the proxy).

    Returns ``None`` for anything that is not a valid IP (e.g. Unix sockets).
    """
    host = request.client.host if request.client else None
    if host is None:
        return None
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


# ───────────────────────── CSRF ─────────────────────────


async def require_csrf(request: Request, ctx: Ctx) -> None:
    """Double-submit check for state-changing requests made with the session cookie."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    cookie = request.cookies.get(csrf_cookie_name(ctx.settings))
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not constant_time_equals(cookie, header):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF validation failed")


# ───────────────────────── sessions ─────────────────────────


async def _resolve(request: Request, ctx: AppContext, db: AsyncSession) -> UserSession:
    token = request.cookies.get(session_cookie_name(ctx.settings))
    sess = await ctx.auth.resolve_session(db, token)
    if sess is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    return sess


async def pending_or_verified_session(request: Request, ctx: Ctx, db: DB) -> UserSession:
    return await _resolve(request, ctx, db)


async def verified_session(request: Request, ctx: Ctx, db: DB) -> UserSession:
    sess = await _resolve(request, ctx, db)
    if sess.mfa_verified_at is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "MFA required")
    return sess


async def step_up_session(
    sess: Annotated[UserSession, Depends(verified_session)], ctx: Ctx
) -> UserSession:
    """For sensitive actions (mode changes, approvals, kill-switch clear) from Phase 4."""
    if not ctx.auth.has_recent_mfa(sess):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "recent MFA verification required")
    return sess


PendingSession = Annotated[UserSession, Depends(pending_or_verified_session)]
VerifiedSession = Annotated[UserSession, Depends(verified_session)]
StepUpSession = Annotated[UserSession, Depends(step_up_session)]
