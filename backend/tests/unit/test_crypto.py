import os

import pytest

from app.core.crypto import (
    DecryptionError,
    EncryptedBlob,
    EnvelopeCipher,
    LocalKeyProvider,
    build_cipher,
)


def _cipher(key: bytes | None = None) -> EnvelopeCipher:
    return EnvelopeCipher(LocalKeyProvider(key or os.urandom(32)))


def test_roundtrip() -> None:
    c = _cipher()
    blob = c.encrypt(b"secret-value", "user:1:mfa")
    assert b"secret-value" not in blob
    assert c.decrypt(blob, "user:1:mfa") == b"secret-value"


def test_each_encryption_is_unique() -> None:
    c = _cipher()
    assert c.encrypt(b"x", "a") != c.encrypt(b"x", "a")


def test_wrong_context_fails() -> None:
    c = _cipher()
    blob = c.encrypt(b"secret", "user:1:mfa")
    with pytest.raises(DecryptionError):
        c.decrypt(blob, "user:2:mfa")


def test_tampered_ciphertext_fails() -> None:
    c = _cipher()
    blob = bytearray(c.encrypt(b"secret", "ctx"))
    blob[-1] ^= 0x01
    with pytest.raises(DecryptionError):
        c.decrypt(bytes(blob), "ctx")


def test_wrong_master_key_fails() -> None:
    blob = _cipher().encrypt(b"secret", "ctx")
    with pytest.raises(DecryptionError):
        _cipher().decrypt(blob, "ctx")


def test_truncated_blob_fails() -> None:
    with pytest.raises(DecryptionError):
        EncryptedBlob.from_bytes(b"\x01\x00")


def test_build_cipher_requires_key_when_not_ephemeral() -> None:
    with pytest.raises(RuntimeError):
        build_cipher(None, allow_ephemeral=False)
