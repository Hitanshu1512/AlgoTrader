"""Application configuration.

All settings come from environment variables (prefix ``ALGOTRADER_``). Any setting can
instead be read from a file by setting ``ALGOTRADER_<NAME>_FILE``, which is how Docker /
cloud secrets are mounted. Secrets are never given defaults that would work in production.
"""

from __future__ import annotations

import base64
import os
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class TradingEnv(StrEnum):
    PAPER = "paper"
    LIVE = "live"


_FILE_SUFFIX = "_FILE"
_PREFIX = "ALGOTRADER_"


def _load_file_overrides() -> dict[str, Any]:
    """Map ALGOTRADER_X_FILE=/path → {"x": <file contents>}."""
    values: dict[str, Any] = {}
    for key, path in os.environ.items():
        if key.startswith(_PREFIX) and key.endswith(_FILE_SUFFIX):
            name = key[len(_PREFIX) : -len(_FILE_SUFFIX)].lower()
            values[name] = Path(path).read_text(encoding="utf-8").strip()
    return values


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix=_PREFIX, env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: AppEnv = AppEnv.DEVELOPMENT
    # Selected once at process start. Paper processes never receive live broker credentials.
    trading_env: TradingEnv = TradingEnv.PAPER

    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://algotrader:algotrader@localhost:5432/algotrader"
    )
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")

    # 32-byte key, base64-encoded. Used by the local envelope-encryption key provider.
    # In production this is replaced by AWS KMS (Phase 7); it must never be committed.
    master_key: SecretStr | None = None

    public_origin: str = "http://localhost:3000"
    cookie_secure: bool = True

    session_absolute_ttl_minutes: int = Field(default=12 * 60, ge=5, le=24 * 60)
    session_idle_timeout_minutes: int = Field(default=60, ge=5, le=12 * 60)
    mfa_pending_ttl_minutes: int = Field(default=10, ge=1, le=30)
    step_up_mfa_minutes: int = Field(default=15, ge=1, le=120)

    login_max_attempts: int = Field(default=5, ge=1, le=50)
    login_window_seconds: int = Field(default=15 * 60, ge=60)

    log_level: str = "INFO"
    log_json: bool = True

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        return (init_settings, lambda: _load_file_overrides(), env_settings, dotenv_settings)

    @field_validator("master_key")
    @classmethod
    def _validate_master_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        try:
            raw = base64.b64decode(value.get_secret_value(), validate=True)
        except ValueError as exc:
            raise ValueError("master_key must be valid base64") from exc
        if len(raw) != 32:
            raise ValueError("master_key must decode to exactly 32 bytes")
        return value

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.app_env in (AppEnv.STAGING, AppEnv.PRODUCTION):
            if not self.cookie_secure:
                raise ValueError("cookie_secure must be true outside development/test")
            if self.master_key is None:
                raise ValueError("master_key is required outside development/test")
            if not self.public_origin.startswith("https://"):
                raise ValueError("public_origin must be https outside development/test")
        return self

    @property
    def master_key_bytes(self) -> bytes | None:
        if self.master_key is None:
            return None
        return base64.b64decode(self.master_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
