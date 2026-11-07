"""Owner authentication: password → TOTP MFA → session.

Session lifecycle
-----------------
1. ``login`` verifies the password and creates a session with ``mfa_verified_at = NULL``.
   Such a session can only reach MFA endpoints, and it expires after a few minutes.
2. ``verify_mfa`` (or first-time ``confirm_enrollment``) marks the session verified and
   **rotates** its token, preventing session fixation.
3. Fully verified sessions have an idle timeout and an absolute lifetime.
4. Sensitive actions require a step-up: MFA verified within the last N minutes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.audit.service import Actor
from app.auth.rate_limit import LoginRateLimiter
from app.core.config import Settings
from app.core.crypto import EnvelopeCipher
from app.core.security import (
    hash_password,
    hash_token,
    new_session_token,
    new_totp_secret,
    password_needs_rehash,
    totp_provisioning_uri,
    totp_qr_svg_data_uri,
    validate_password_strength,
    verify_password,
    verify_totp,
)
from app.db.models import User, UserSession


class AuthError(Exception):
    """Generic authentication failure. Messages are deliberately uninformative."""


class RateLimitedError(AuthError):
    pass


class OwnerExistsError(Exception):
    pass


@dataclass(frozen=True)
class IssuedSession:
    session: UserSession
    token: str


@dataclass(frozen=True)
class EnrollmentInfo:
    secret: str
    otpauth_uri: str
    qr_svg_data_uri: str


def _now() -> datetime:
    return datetime.now(UTC)


def _mfa_aad(user_id: uuid.UUID) -> str:
    return f"user:{user_id}:mfa"


class AuthService:
    def __init__(
        self, settings: Settings, cipher: EnvelopeCipher, limiter: LoginRateLimiter
    ) -> None:
        self._settings = settings
        self._cipher = cipher
        self._limiter = limiter

    # ───────────────────────── owner management ─────────────────────────

    async def create_owner(self, db: AsyncSession, email: str, password: str) -> User:
        email = email.strip().lower()
        validate_password_strength(password, email)
        existing = (
            await db.execute(select(User).where(User.role == "owner", User.is_active))
        ).scalar_one_or_none()
        if existing is not None:
            raise OwnerExistsError("an active owner already exists")
        user = User(email=email, password_hash=hash_password(password), role="owner")
        db.add(user)
        await db.flush()
        await audit.record(
            db,
            actor=Actor.CLI,
            action="OWNER_CREATED",
            user_id=user.id,
            entity_type="user",
            entity_id=str(user.id),
            after={"email": email},
        )
        return user

    async def reset_mfa(self, db: AsyncSession, email: str) -> None:
        user = await self._user_by_email(db, email)
        if user is None:
            raise AuthError("no such user")
        user.mfa_enabled = False
        user.mfa_secret_enc = None
        user.mfa_pending_secret_enc = None
        user.mfa_last_used_step = None
        await self.revoke_all_sessions(db, user.id, reason="mfa_reset")
        await audit.record(
            db,
            actor=Actor.CLI,
            action="MFA_RESET",
            user_id=user.id,
            entity_type="user",
            entity_id=str(user.id),
        )

    async def change_password(self, db: AsyncSession, email: str, new_password: str) -> None:
        user = await self._user_by_email(db, email)
        if user is None:
            raise AuthError("no such user")
        validate_password_strength(new_password, user.email)
        user.password_hash = hash_password(new_password)
        user.password_changed_at = _now()
        await self.revoke_all_sessions(db, user.id, reason="password_changed")
        await audit.record(
            db,
            actor=Actor.CLI,
            action="PASSWORD_CHANGED",
            user_id=user.id,
            entity_type="user",
            entity_id=str(user.id),
        )

    # ───────────────────────── login ─────────────────────────

    async def login(
        self, db: AsyncSession, email: str, password: str, ip: str | None, user_agent: str | None
    ) -> tuple[IssuedSession, User]:
        email = email.strip().lower()
        keys = (f"email:{email}", f"ip:{ip or 'unknown'}")
        if await self._limiter.is_blocked(*keys):
            await audit.record(
                db, actor=Actor.USER, action="LOGIN_RATE_LIMITED", ip=ip, after={"email": email}
            )
            await db.commit()
            raise RateLimitedError("too many attempts")

        user = await self._user_by_email(db, email)
        ok = verify_password(user.password_hash if user else None, password)
        if not ok or user is None or not user.is_active:
            await self._limiter.record_failure(*keys)
            await audit.record(
                db,
                actor=Actor.USER,
                action="LOGIN_FAILED",
                ip=ip,
                user_id=user.id if user else None,
                after={"email": email},
            )
            await db.commit()
            raise AuthError("invalid credentials")

        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)

        issued = await self._new_session(
            db, user, ip, user_agent, ttl=timedelta(minutes=self._settings.mfa_pending_ttl_minutes)
        )
        await audit.record(
            db,
            actor=Actor.USER,
            action="LOGIN_PASSWORD_OK",
            user_id=user.id,
            session_id=issued.session.id,
            ip=ip,
        )
        await db.commit()
        return issued, user

    # ───────────────────────── MFA ─────────────────────────

    async def start_enrollment(self, db: AsyncSession, sess: UserSession) -> EnrollmentInfo:
        user = sess.user
        if user.mfa_enabled:
            raise AuthError("MFA already enrolled")
        secret = new_totp_secret()
        user.mfa_pending_secret_enc = self._cipher.encrypt(secret.encode(), _mfa_aad(user.id))
        await db.commit()
        uri = totp_provisioning_uri(secret, user.email)
        return EnrollmentInfo(
            secret=secret, otpauth_uri=uri, qr_svg_data_uri=totp_qr_svg_data_uri(uri)
        )

    async def confirm_enrollment(
        self, db: AsyncSession, sess: UserSession, code: str, ip: str | None
    ) -> IssuedSession:
        user = sess.user
        if user.mfa_enabled or user.mfa_pending_secret_enc is None:
            raise AuthError("no enrollment in progress")
        secret = self._cipher.decrypt(user.mfa_pending_secret_enc, _mfa_aad(user.id)).decode()
        step = verify_totp(secret, code, None)
        if step is None:
            await self._mfa_failure(db, sess, ip, "MFA_ENROLL_FAILED")
        user.mfa_secret_enc = user.mfa_pending_secret_enc
        user.mfa_pending_secret_enc = None
        user.mfa_enabled = True
        user.mfa_last_used_step = step
        await audit.record(
            db, actor=Actor.USER, action="MFA_ENROLLED", user_id=user.id, session_id=sess.id, ip=ip
        )
        return await self._promote(db, sess, ip)

    async def verify_mfa(
        self, db: AsyncSession, sess: UserSession, code: str, ip: str | None
    ) -> IssuedSession:
        await self._check_code(db, sess, code, ip, failure_action="MFA_FAILED")
        return await self._promote(db, sess, ip)

    async def step_up(self, db: AsyncSession, sess: UserSession, code: str, ip: str | None) -> None:
        await self._check_code(db, sess, code, ip, failure_action="STEP_UP_FAILED")
        sess.mfa_verified_at = _now()
        await audit.record(
            db,
            actor=Actor.USER,
            action="STEP_UP_OK",
            user_id=sess.user_id,
            session_id=sess.id,
            ip=ip,
        )
        await db.commit()

    async def _check_code(
        self, db: AsyncSession, sess: UserSession, code: str, ip: str | None, failure_action: str
    ) -> None:
        user = sess.user
        if not user.mfa_enabled or user.mfa_secret_enc is None:
            raise AuthError("MFA not enrolled")
        key = f"mfa:{user.id}"
        if await self._limiter.is_blocked(key):
            raise RateLimitedError("too many attempts")
        secret = self._cipher.decrypt(user.mfa_secret_enc, _mfa_aad(user.id)).decode()
        step = verify_totp(secret, code, user.mfa_last_used_step)
        if step is None:
            await self._mfa_failure(db, sess, ip, failure_action)
        user.mfa_last_used_step = step
        await self._limiter.reset(key)

    async def _mfa_failure(
        self, db: AsyncSession, sess: UserSession, ip: str | None, action: str
    ) -> NoReturn:
        await self._limiter.record_failure(f"mfa:{sess.user_id}")
        await audit.record(
            db, actor=Actor.USER, action=action, user_id=sess.user_id, session_id=sess.id, ip=ip
        )
        await db.commit()
        raise AuthError("invalid code")

    async def _promote(self, db: AsyncSession, sess: UserSession, ip: str | None) -> IssuedSession:
        """Mark session MFA-verified and rotate its token (anti-fixation)."""
        now = _now()
        token = new_session_token()
        sess.token_hash = hash_token(token)
        sess.mfa_verified_at = now
        sess.last_seen_at = now
        sess.expires_at = now + timedelta(minutes=self._settings.session_absolute_ttl_minutes)
        await audit.record(
            db,
            actor=Actor.USER,
            action="LOGIN_SUCCESS",
            user_id=sess.user_id,
            session_id=sess.id,
            ip=ip,
        )
        await db.commit()
        return IssuedSession(sess, token)

    # ───────────────────────── sessions ─────────────────────────

    async def resolve_session(self, db: AsyncSession, token: str | None) -> UserSession | None:
        """Return a live session for a cookie token, enforcing all expiry rules."""
        if not token:
            return None
        sess = (
            await db.execute(select(UserSession).where(UserSession.token_hash == hash_token(token)))
        ).scalar_one_or_none()
        if sess is None or sess.revoked_at is not None or not sess.user.is_active:
            return None
        now = _now()
        if now >= sess.expires_at:
            return None
        if sess.mfa_verified_at is not None:
            idle = timedelta(minutes=self._settings.session_idle_timeout_minutes)
            if now - sess.last_seen_at > idle:
                sess.revoked_at = now
                sess.revoke_reason = "idle_timeout"
                await db.commit()
                return None
            if now - sess.last_seen_at > timedelta(seconds=60):
                sess.last_seen_at = now
                await db.commit()
        return sess

    def has_recent_mfa(self, sess: UserSession) -> bool:
        if sess.mfa_verified_at is None:
            return False
        window = timedelta(minutes=self._settings.step_up_mfa_minutes)
        return _now() - sess.mfa_verified_at <= window

    async def logout(self, db: AsyncSession, sess: UserSession, ip: str | None) -> None:
        sess.revoked_at = _now()
        sess.revoke_reason = "logout"
        await audit.record(
            db, actor=Actor.USER, action="LOGOUT", user_id=sess.user_id, session_id=sess.id, ip=ip
        )
        await db.commit()

    async def revoke_all_sessions(self, db: AsyncSession, user_id: uuid.UUID, reason: str) -> None:
        await db.execute(
            update(UserSession)
            .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            .values(revoked_at=_now(), revoke_reason=reason)
        )

    async def _new_session(
        self, db: AsyncSession, user: User, ip: str | None, user_agent: str | None, ttl: timedelta
    ) -> IssuedSession:
        now = _now()
        token = new_session_token()
        sess = UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            ip=ip,
            user_agent=(user_agent or "")[:512] or None,
            created_at=now,
            last_seen_at=now,
            expires_at=now + ttl,
        )
        sess.user = user
        db.add(sess)
        await db.flush()
        return IssuedSession(sess, token)

    async def _user_by_email(self, db: AsyncSession, email: str) -> User | None:
        return (
            await db.execute(select(User).where(User.email == email.strip().lower()))
        ).scalar_one_or_none()
