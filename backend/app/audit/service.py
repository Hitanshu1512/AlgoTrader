"""Hash-chained, append-only audit trail.

``row_hash = SHA-256(prev_hash || canonical_json(row))``. Inserts are serialised with a
transaction-scoped advisory lock so the chain never forks. :func:`verify_chain` recomputes
every hash; any edit, deletion or reordering of rows breaks verification from that point on.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import redact
from app.db.models import AuditLog

_CHAIN_LOCK_KEY = 0x41_55_44_49_54  # "AUDIT"


class Actor:
    USER = "user"
    SYSTEM = "system"
    CLI = "cli"
    ENGINE = "engine"
    EXECUTOR = "executor"
    RECONCILER = "reconciler"
    SCHEDULER = "scheduler"


def _canonical(row: dict[str, Any]) -> bytes:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), default=str).encode()


def _hash_fields(entry: AuditLog) -> dict[str, Any]:
    return {
        "user_id": str(entry.user_id) if entry.user_id else None,
        "session_id": str(entry.session_id) if entry.session_id else None,
        "actor": entry.actor,
        "action": entry.action,
        "entity_type": entry.entity_type,
        "entity_id": entry.entity_id,
        "before": entry.before,
        "after": entry.after,
        "ip": str(entry.ip) if entry.ip else None,
        "occurred_at": entry.occurred_at.astimezone(UTC).isoformat(timespec="microseconds"),
    }


def compute_hash(prev_hash: bytes | None, entry: AuditLog) -> bytes:
    return hashlib.sha256((prev_hash or b"") + _canonical(_hash_fields(entry))).digest()


async def record(
    db: AsyncSession,
    *,
    actor: str,
    action: str,
    user_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditLog:
    """Append an audit entry inside the caller's transaction (caller commits).

    ``before``/``after`` are passed through the log redactor, so secrets can never be
    persisted into the audit trail even by mistake.
    """
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CHAIN_LOCK_KEY})
    prev_hash = (
        await db.execute(select(AuditLog.row_hash).order_by(AuditLog.id.desc()).limit(1))
    ).scalar_one_or_none()
    entry = AuditLog(
        user_id=user_id,
        session_id=session_id,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=redact(before) if before is not None else None,
        after=redact(after) if after is not None else None,
        ip=ip,
        occurred_at=datetime.now(UTC),
        prev_hash=prev_hash,
    )
    entry.row_hash = compute_hash(prev_hash, entry)
    db.add(entry)
    await db.flush()
    return entry


@dataclass(frozen=True)
class ChainVerification:
    valid: bool
    entries_checked: int
    first_broken_id: int | None = None


async def verify_chain(db: AsyncSession, batch_size: int = 1000) -> ChainVerification:
    prev_hash: bytes | None = None
    checked = 0
    last_id = 0
    while True:
        rows = (
            (
                await db.execute(
                    select(AuditLog)
                    .where(AuditLog.id > last_id)
                    .order_by(AuditLog.id)
                    .limit(batch_size)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return ChainVerification(True, checked)
        for entry in rows:
            if entry.prev_hash != prev_hash or compute_hash(prev_hash, entry) != entry.row_hash:
                return ChainVerification(False, checked, entry.id)
            prev_hash = entry.row_hash
            checked += 1
            last_id = entry.id
