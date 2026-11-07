import pyotp
import pytest

from app.core.security import (
    WeakPasswordError,
    hash_password,
    hash_token,
    validate_password_strength,
    verify_password,
    verify_totp,
)


def test_password_hash_roundtrip() -> None:
    h = hash_password("Sup3r-Secret-Pass")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "Sup3r-Secret-Pass")
    assert not verify_password(h, "wrong-password")


def test_verify_without_hash_is_false() -> None:
    assert not verify_password(None, "anything")


def test_corrupt_hash_is_false() -> None:
    assert not verify_password("not-a-hash", "anything")


@pytest.mark.parametrize("pw", ["short1A!", "alllowercaseletters", "owner-Name-12345"])
def test_weak_passwords_rejected(pw: str) -> None:
    with pytest.raises(WeakPasswordError):
        validate_password_strength(pw, "name@example.com")


def test_strong_password_accepted() -> None:
    validate_password_strength("Correct-Horse-42-battery", "owner@example.com")


def test_token_hash_deterministic_and_distinct() -> None:
    assert hash_token("a") == hash_token("a")
    assert hash_token("a") != hash_token("b")


def test_totp_accepts_current_and_adjacent_steps() -> None:
    secret = pyotp.random_base32()
    now = 1_800_000_000.0
    totp = pyotp.TOTP(secret)
    assert verify_totp(secret, totp.at(now), None, now=now) == int(now // 30)
    assert verify_totp(secret, totp.at(now - 30), None, now=now) is not None
    assert verify_totp(secret, totp.at(now + 30), None, now=now) is not None
    assert verify_totp(secret, totp.at(now - 90), None, now=now) is None


def test_totp_replay_rejected() -> None:
    secret = pyotp.random_base32()
    now = 1_800_000_000.0
    code = pyotp.TOTP(secret).at(now)
    step = verify_totp(secret, code, None, now=now)
    assert step is not None
    assert verify_totp(secret, code, step, now=now) is None


@pytest.mark.parametrize("code", ["", "12345", "abcdef", "1234567"])
def test_totp_malformed(code: str) -> None:
    assert verify_totp(pyotp.random_base32(), code, None) is None
