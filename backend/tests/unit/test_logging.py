from app.core.logging import REDACTED, redact


def test_sensitive_keys_redacted_recursively() -> None:
    data = {
        "user": "a",
        "password": "p",
        "nested": {"access_token": "t", "api_secret": "s", "items": [{"totp": "123456"}]},
        "session_id": "keep-me",
        "status_code": 200,
    }
    out = redact(data)
    assert out["user"] == "a"
    assert out["password"] == REDACTED
    assert out["nested"]["access_token"] == REDACTED
    assert out["nested"]["api_secret"] == REDACTED
    assert out["nested"]["items"][0]["totp"] == REDACTED
    assert out["session_id"] == "keep-me"
    assert out["status_code"] == 200


def test_bearer_and_jwt_scrubbed_from_strings() -> None:
    msg = (
        "call failed: Authorization Bearer abcdefghijklmnop12345 "
        "token eyJhbGciOi.eyJzdWIiOi.c2lnbmF0dXJl"
    )
    out = redact(msg)
    assert "abcdefghijklmnop12345" not in out
    assert "eyJhbGciOi.eyJzdWIiOi.c2lnbmF0dXJl" not in out
