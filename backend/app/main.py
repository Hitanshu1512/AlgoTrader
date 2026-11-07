from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from redis.asyncio import Redis

from app import __version__
from app.api import auth, system, ws
from app.api.deps import AppContext
from app.auth.rate_limit import LoginRateLimiter
from app.auth.service import AuthService
from app.core.config import AppEnv, Settings, get_settings
from app.core.crypto import build_cipher
from app.core.events import EventBus
from app.core.logging import configure_logging, get_logger
from app.db.session import create_engine, create_sessionmaker

log = get_logger(__name__)

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def build_context(settings: Settings, redis: Redis | None = None) -> AppContext:
    engine = create_engine(settings.database_url.get_secret_value())
    redis = redis or Redis.from_url(settings.redis_url.get_secret_value(), decode_responses=True)
    cipher = build_cipher(
        settings.master_key_bytes,
        allow_ephemeral=settings.app_env in (AppEnv.DEVELOPMENT, AppEnv.TEST),
    )
    limiter = LoginRateLimiter(redis, settings.login_max_attempts, settings.login_window_seconds)
    return AppContext(
        settings=settings,
        engine=engine,
        sessionmaker=create_sessionmaker(engine),
        redis=redis,
        cipher=cipher,
        auth=AuthService(settings, cipher, limiter),
        events=EventBus(redis),
    )


def create_app(settings: Settings | None = None, context: AppContext | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        ctx = context or build_context(settings)
        app.state.ctx = ctx
        if settings.master_key is None:
            log.warning(
                "ephemeral_master_key_in_use",
                detail="encrypted values (MFA secrets) will not survive a restart",
            )
        log.info(
            "api_started",
            version=__version__,
            app_env=settings.app_env.value,
            trading_env=settings.trading_env.value,
        )
        try:
            yield
        finally:
            if context is None:
                await ctx.redis.aclose()
                await ctx.engine.dispose()

    is_dev = settings.app_env in (AppEnv.DEVELOPMENT, AppEnv.TEST)
    app = FastAPI(
        title="AlgoTrader API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if is_dev else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if is_dev else None,
    )

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for key, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response

    for router in (system.router, auth.router, ws.router):
        app.include_router(router, prefix="/api")
    return app
