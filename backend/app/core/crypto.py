"""Envelope encryption for secrets stored in the database.

Each secret is encrypted with a fresh 256-bit data-encryption key (DEK) using AES-256-GCM.
The DEK is wrapped by a :class:`KeyProvider`. In development/staging that is
:class:`LocalKeyProvider` (master key from a secret file / env). Phase 7 adds a KMS provider
with the same interface, so stored blobs need no format change.

Associated data (AAD) binds a ciphertext to its context (e.g. ``user:<id>:mfa``) so a
blob copied into another row fails to decrypt.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_FORMAT_VERSION = 1
_NONCE_LEN = 12


class DecryptionError(Exception):
    """Raised when a blob cannot be authenticated/decrypted."""


class KeyProvider(Protocol):
    key_id: str

    def wrap(self, dek: bytes) -> bytes: ...

    def unwrap(self, wrapped: bytes, key_id: str) -> bytes: ...


class LocalKeyProvider:
    """Wraps DEKs with a locally held 32-byte master key (AES-256-GCM)."""

    def __init__(self, master_key: bytes, key_id: str = "local-v1") -> None:
        if len(master_key) != 32:
            raise ValueError("master key must be 32 bytes")
        self._aead = AESGCM(master_key)
        self.key_id = key_id

    def wrap(self, dek: bytes) -> bytes:
        nonce = os.urandom(_NONCE_LEN)
        return nonce + self._aead.encrypt(nonce, dek, self.key_id.encode())

    def unwrap(self, wrapped: bytes, key_id: str) -> bytes:
        if key_id != self.key_id:
            raise DecryptionError(f"unknown key id {key_id!r}")
        try:
            return self._aead.decrypt(wrapped[:_NONCE_LEN], wrapped[_NONCE_LEN:], key_id.encode())
        except InvalidTag as exc:
            raise DecryptionError("DEK unwrap failed") from exc


@dataclass(frozen=True)
class EncryptedBlob:
    key_id: str
    wrapped_dek: bytes
    nonce: bytes
    ciphertext: bytes

    def to_bytes(self) -> bytes:
        kid = self.key_id.encode()
        return (
            struct.pack(">BHH", _FORMAT_VERSION, len(kid), len(self.wrapped_dek))
            + kid
            + self.wrapped_dek
            + self.nonce
            + self.ciphertext
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> EncryptedBlob:
        try:
            version, kid_len, dek_len = struct.unpack(">BHH", data[:5])
        except struct.error as exc:
            raise DecryptionError("blob too short") from exc
        if version != _FORMAT_VERSION:
            raise DecryptionError(f"unsupported blob version {version}")
        pos = 5
        kid = data[pos : pos + kid_len].decode()
        pos += kid_len
        wrapped = data[pos : pos + dek_len]
        pos += dek_len
        nonce = data[pos : pos + _NONCE_LEN]
        ciphertext = data[pos + _NONCE_LEN :]
        if len(nonce) != _NONCE_LEN or not ciphertext:
            raise DecryptionError("blob truncated")
        return cls(kid, wrapped, nonce, ciphertext)


class EnvelopeCipher:
    def __init__(self, provider: KeyProvider) -> None:
        self._provider = provider

    def encrypt(self, plaintext: bytes, aad: str) -> bytes:
        dek = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(_NONCE_LEN)
        ciphertext = AESGCM(dek).encrypt(nonce, plaintext, aad.encode())
        blob = EncryptedBlob(self._provider.key_id, self._provider.wrap(dek), nonce, ciphertext)
        return blob.to_bytes()

    def decrypt(self, data: bytes, aad: str) -> bytes:
        blob = EncryptedBlob.from_bytes(data)
        dek = self._provider.unwrap(blob.wrapped_dek, blob.key_id)
        try:
            return AESGCM(dek).decrypt(blob.nonce, blob.ciphertext, aad.encode())
        except InvalidTag as exc:
            raise DecryptionError("ciphertext authentication failed") from exc


_DEV_KEY_WARNING_SHOWN = False


def build_cipher(master_key: bytes | None, allow_ephemeral: bool) -> EnvelopeCipher:
    """Create the process-wide cipher.

    With no master key configured, development/test get an *ephemeral* random key:
    anything encrypted is unreadable after restart, which is safe but obviously not
    durable. Staging/production refuse to start without a key (see Settings).
    """
    if master_key is None:
        if not allow_ephemeral:
            raise RuntimeError("no master key configured")
        master_key = os.urandom(32)
        return EnvelopeCipher(LocalKeyProvider(master_key, key_id="ephemeral"))
    return EnvelopeCipher(LocalKeyProvider(master_key))
