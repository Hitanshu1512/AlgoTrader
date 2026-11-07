from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import select, text

from app import __version__
from app.api.deps import DB, Ctx, VerifiedSession
from app.audit.service import verify_chain
from app.db.models import AuditLog

router = APIRouter(tags=["system"])
IST = ZoneInfo("Asia/Kolkata")

ComponentStatus = Literal["ok", "degraded", "down", "not_configured", "not_deployed"]


class Component(BaseModel):
    name: str
    status: ComponentStatus
    latency_ms: float | None = None
    detail: str | None = None


class SystemStatus(BaseModel):
    version: str
    app_env: str
    trading_env: str
    server_time_utc: str
    server_time_ist: str
    components: list[Component]


async def _check_db(ctx: Ctx) -> Component:
    start = time.perf_counter()
    try:
        async with ctx.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return Component(
            name="database", status="ok", latency_ms=round((time.perf_counter() - start) * 1000, 2)
        )
    except Exception as exc:
        return Component(name="database", status="down", detail=type(exc).__name__)


async def _check_redis(ctx: Ctx) -> Component:
    start = time.perf_counter()
    try:
        await ctx.redis.ping()
        return Component(
            name="redis", status="ok", latency_ms=round((time.perf_counter() - start) * 1000, 2)
        )
    except Exception as exc:
        return Component(name="redis", status="down", detail=type(exc).__name__)


async def collect_status(ctx: Ctx) -> SystemStatus:
    now = datetime.now(UTC)
    components = [
        Component(name="api", status="ok"),
        await _check_db(ctx),
        await _check_redis(ctx),
        # Reported honestly until the phases that build them:
        Component(name="broker", status="not_configured", detail="Upstox adapter: Phase 3"),
        Component(name="market_data", status="not_deployed", detail="Phase 3"),
        Component(name="trading_engine", status="not_deployed", detail="Phase 4"),
    ]
    return SystemStatus(
        version=__version__,
        app_env=ctx.settings.app_env.value,
        trading_env=ctx.settings.trading_env.value,
        server_time_utc=now.isoformat(),
        server_time_ist=now.astimezone(IST).isoformat(),
        components=components,
    )


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: the process is up. No dependencies checked."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(ctx: Ctx, response: Response) -> dict[str, str]:
    """Readiness: database and Redis reachable. Reveals nothing beyond ok/unavailable."""
    db, redis = await _check_db(ctx), await _check_redis(ctx)
    if db.status != "ok" or redis.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable"}
    return {"status": "ok"}


@router.get("/system/status", response_model=SystemStatus)
async def system_status(_: VerifiedSession, ctx: Ctx) -> SystemStatus:
    return await collect_status(ctx)


class AuditEntry(BaseModel):
    id: int
    occurred_at: str
    actor: str
    action: str
    entity_type: str | None
    entity_id: str | None
    ip: str | None


class AuditVerification(BaseModel):
    valid: bool
    entries_checked: int
    first_broken_id: int | None


@router.get("/audit", response_model=list[AuditEntry])
async def recent_audit(_: VerifiedSession, db: DB, limit: int = 50) -> list[AuditEntry]:
    limit = max(1, min(limit, 500))
    rows = (
        (await db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)))
        .scalars()
        .all()
    )
    return [
        AuditEntry(
            id=r.id,
            occurred_at=r.occurred_at.isoformat(),
            actor=r.actor,
            action=r.action,
            entity_type=r.entity_type,
            entity_id=r.entity_id,
            ip=str(r.ip) if r.ip else None,
        )
        for r in rows
    ]


@router.get("/audit/verify", response_model=AuditVerification)
async def verify_audit(_: VerifiedSession, db: DB) -> AuditVerification:
    result = await verify_chain(db)
    return AuditVerification(
        valid=result.valid,
        entries_checked=result.entries_checked,
        first_broken_id=result.first_broken_id,
    )
