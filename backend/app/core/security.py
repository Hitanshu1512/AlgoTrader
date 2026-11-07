"""Password hashing, session tokens and TOTP helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

import pyotp
import segno
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# OWASP-recommended Argon2id parameters (m=64 MiB, t=3, p=4).
_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4)
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

MIN_PASSWORD_LENGTH = 12
TOTP_ISSUER = "AlgoTrader"
TOTP_INTERVAL = 30


class WeakPasswordError(ValueError):
    pass


def validate_password_strength(password: str, email: str | None = None) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > 256:
        raise WeakPasswordError("password too long")
    classes = sum(
        [
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ]
    )
    if classes < 3:
        raise WeakPasswordError(
            "password must mix at least three of: lowercase, uppercase, digits, symbols"
        )
    if email and email.split("@")[0].lower() in password.lower():
        raise WeakPasswordError("password must not contain the email name")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-work verification; a missing hash still costs one Argon2 run."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# ─────────────────────────── TOTP ───────────────────────────


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, account_name: str) -> str:
    return pyotp.TOTP(secret, interval=TOTP_INTERVAL).provisioning_uri(
        name=account_name, issuer_name=TOTP_ISSUER
    )


def totp_qr_svg_data_uri(uri: str) -> str:
    return str(segno.make(uri, error="m").svg_data_uri(scale=5, border=2))


def verify_totp(
    secret: str, code: str, last_used_step: int | None, now: float | None = None
) -> int | None:
    """Verify a TOTP code allowing ±1 step of clock drift.

    Returns the matched time-step on success, or ``None``. A code whose step is not newer
    than ``last_used_step`` is rejected, so each code can be used only once (replay
    protection).
    """
    code = code.strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return None
    now = time.time() if now is None else now
    totp = pyotp.TOTP(secret, interval=TOTP_INTERVAL)
    current_step = int(now // TOTP_INTERVAL)
    for step in (current_step - 1, current_step, current_step + 1):
        if hmac.compare_digest(totp.at(step * TOTP_INTERVAL), code):
            if last_used_step is not None and step <= last_used_step:
                return None
            return step
    return None
