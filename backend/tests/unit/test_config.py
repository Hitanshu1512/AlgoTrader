import base64
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import AppEnv, Settings

KEY = base64.b64encode(os.urandom(32)).decode()


def test_production_requires_secure_settings() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env=AppEnv.PRODUCTION, cookie_secure=True, public_origin="https://x.in")
    with pytest.raises(ValidationError):
        Settings(
            app_env=AppEnv.PRODUCTION,
            master_key=KEY,
            cookie_secure=False,
            public_origin="https://x.in",
        )
    with pytest.raises(ValidationError):
        Settings(app_env=AppEnv.PRODUCTION, master_key=KEY, public_origin="http://x.in")
    ok = Settings(app_env=AppEnv.PRODUCTION, master_key=KEY, public_origin="https://x.in")
    assert ok.master_key_bytes is not None and len(ok.master_key_bytes) == 32


def test_master_key_must_be_32_bytes() -> None:
    with pytest.raises(ValidationError):
        Settings(master_key=base64.b64encode(b"short").decode())


def test_trading_env_defaults_to_paper() -> None:
    assert Settings().trading_env.value == "paper"


def test_secret_from_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "key"
    f.write_text(KEY + "\n")
    monkeypatch.setenv("ALGOTRADER_MASTER_KEY_FILE", str(f))
    s = Settings()
    assert s.master_key is not None and s.master_key.get_secret_value() == KEY
