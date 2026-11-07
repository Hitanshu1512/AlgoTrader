import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.api.deps import AppContext
from app.audit import service as audit


async def test_chain_records_and_verifies(ctx: AppContext) -> None:
    async with ctx.sessionmaker() as db:
        for i in range(5):
            await audit.record(db, actor="system", action=f"TEST_{i}", after={"i": i})
        await db.commit()
        result = await audit.verify_chain(db)
    assert result.valid and result.entries_checked == 5


async def test_secrets_never_stored_in_audit(ctx: AppContext) -> None:
    async with ctx.sessionmaker() as db:
        entry = await audit.record(
            db, actor="system", action="X", after={"access_token": "abc", "note": "fine"}
        )
        await db.commit()
    assert entry.after == {"access_token": "[REDACTED]", "note": "fine"}


async def test_update_and_delete_blocked_by_trigger(ctx: AppContext) -> None:
    async with ctx.sessionmaker() as db:
        await audit.record(db, actor="system", action="X")
        await db.commit()
    for stmt in ("UPDATE audit_logs SET action = 'Y'", "DELETE FROM audit_logs"):
        async with ctx.sessionmaker() as db:
            with pytest.raises(DBAPIError, match="append-only"):
                await db.execute(text(stmt))


async def test_tampering_detected(ctx: AppContext) -> None:
    async with ctx.sessionmaker() as db:
        for i in range(3):
            await audit.record(db, actor="system", action=f"A{i}")
        await db.commit()
    # Simulate an attacker with table-owner rights bypassing the trigger.
    async with ctx.engine.begin() as conn:
        await conn.execute(text("ALTER TABLE audit_logs DISABLE TRIGGER USER"))
        await conn.execute(text("UPDATE audit_logs SET action = 'FORGED' WHERE id = 2"))
        await conn.execute(text("ALTER TABLE audit_logs ENABLE TRIGGER USER"))
    async with ctx.sessionmaker() as db:
        result = await audit.verify_chain(db)
    assert not result.valid and result.first_broken_id == 2


async def test_concurrent_writers_keep_chain_linear(ctx: AppContext) -> None:
    async def writer(i: int) -> None:
        async with ctx.sessionmaker() as db:
            await audit.record(db, actor="system", action=f"C{i}")
            await db.commit()

    await asyncio.gather(*(writer(i) for i in range(10)))
    async with ctx.sessionmaker() as db:
        result = await audit.verify_chain(db)
    assert result.valid and result.entries_checked == 10
