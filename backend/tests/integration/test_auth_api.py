from datetime import timedelta

from httpx import AsyncClient, Response
from sqlalchemy import select, update

from app.api.deps import AppContext
from app.auth.service import OwnerExistsError
from app.db.models import AuditLog, UserSession
from tests.conftest import (
    ORIGIN,
    OWNER_EMAIL,
    OWNER_PASSWORD,
    FakeClock,
    create_owner,
    csrf_headers,
    login_and_enroll,
    totp_now,
)


async def _get_with_token(client: AsyncClient, path: str, token: str | None) -> Response:
    """Request with only the given session cookie, as an attacker holding an old token would."""
    async with AsyncClient(
        transport=client._transport, base_url=ORIGIN, cookies={"at_session": token or ""}
    ) as other:
        return await other.get(path)


async def _actions(ctx: AppContext) -> list[str]:
    async with ctx.sessionmaker() as db:
        return list((await db.execute(select(AuditLog.action).order_by(AuditLog.id))).scalars())


async def test_health_and_ready(client: AsyncClient) -> None:
    assert (await client.get("/api/health")).json() == {"status": "ok"}
    r = await client.get("/api/ready")
    assert r.status_code == 200
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"


async def test_protected_endpoints_require_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/system/status")).status_code == 401
    assert (await client.get("/api/audit")).status_code == 401
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_only_one_owner(ctx: AppContext) -> None:
    await create_owner(ctx)
    async with ctx.sessionmaker() as db:
        try:
            await ctx.auth.create_owner(db, "second@example.com", OWNER_PASSWORD)
            raise AssertionError("second owner should be refused")
        except OwnerExistsError:
            pass


async def test_full_enrollment_flow(client: AsyncClient, ctx: AppContext, clock: FakeClock) -> None:
    await create_owner(ctx)
    r = await client.post(
        "/api/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}
    )
    assert r.status_code == 200
    assert r.json()["mfa_verified"] is False and r.json()["mfa_enrolled"] is False

    # A password-only session cannot reach anything beyond MFA endpoints.
    assert (await client.get("/api/system/status")).status_code == 401

    r = await client.post("/api/auth/mfa/enroll/start", headers=csrf_headers(client))
    secret = r.json()["secret"]
    assert r.json()["qr_svg_data_uri"].startswith("data:image/svg+xml")
    pending_token = client.cookies.get("at_session")

    r = await client.post(
        "/api/auth/mfa/enroll/confirm", json={"code": "000000"}, headers=csrf_headers(client)
    )
    assert r.status_code == 401

    r = await client.post(
        "/api/auth/mfa/enroll/confirm",
        json={"code": totp_now(secret, clock)},
        headers=csrf_headers(client),
    )
    assert r.status_code == 200 and r.json()["mfa_verified"] is True

    # Token rotated on promotion: the pre-MFA token is dead.
    assert client.cookies.get("at_session") != pending_token
    assert (await _get_with_token(client, "/api/auth/me", pending_token)).status_code == 401

    r = await client.get("/api/system/status")
    assert r.status_code == 200
    names = {c["name"]: c["status"] for c in r.json()["components"]}
    assert names["database"] == "ok" and names["redis"] == "ok"
    assert names["broker"] == "not_configured"
    assert r.json()["trading_env"] == "paper"

    assert {
        "OWNER_CREATED",
        "LOGIN_PASSWORD_OK",
        "MFA_ENROLL_FAILED",
        "MFA_ENROLLED",
        "LOGIN_SUCCESS",
    } <= set(await _actions(ctx))


async def test_subsequent_login_requires_totp(
    client: AsyncClient, ctx: AppContext, clock: FakeClock
) -> None:
    secret = await login_and_enroll(client, ctx, clock)
    await client.post("/api/auth/logout", headers=csrf_headers(client))

    await client.post("/api/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
    r = await client.post("/api/auth/mfa/enroll/start", headers=csrf_headers(client))
    assert r.status_code == 409  # cannot re-enrol (would replace the second factor)

    r = await client.post(
        "/api/auth/mfa/verify", json={"code": totp_now(secret, clock)}, headers=csrf_headers(client)
    )
    assert r.status_code == 200
    assert (await client.get("/api/system/status")).status_code == 200


async def test_totp_code_cannot_be_replayed(
    client: AsyncClient, ctx: AppContext, clock: FakeClock
) -> None:
    secret = await login_and_enroll(client, ctx, clock)
    code = totp_now(secret, clock)
    r = await client.post("/api/auth/step-up", json={"code": code}, headers=csrf_headers(client))
    assert r.status_code == 200
    r = await client.post("/api/auth/step-up", json={"code": code}, headers=csrf_headers(client))
    assert r.status_code == 401


async def test_wrong_password_and_rate_limit(client: AsyncClient, ctx: AppContext) -> None:
    await create_owner(ctx)
    for _ in range(ctx.settings.login_max_attempts):
        r = await client.post("/api/auth/login", json={"email": OWNER_EMAIL, "password": "nope"})
        assert r.status_code == 401
    # Even the correct password is refused while blocked.
    r = await client.post(
        "/api/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}
    )
    assert r.status_code == 429
    actions = await _actions(ctx)
    assert actions.count("LOGIN_FAILED") == ctx.settings.login_max_attempts
    assert "LOGIN_RATE_LIMITED" in actions


async def test_unknown_user_gets_same_error(client: AsyncClient, ctx: AppContext) -> None:
    await create_owner(ctx)
    r1 = await client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "x"})
    r2 = await client.post("/api/auth/login", json={"email": OWNER_EMAIL, "password": "x"})
    assert r1.status_code == r2.status_code == 401
    assert r1.json() == r2.json()


async def test_csrf_required_for_state_changes(
    client: AsyncClient, ctx: AppContext, clock: FakeClock
) -> None:
    await login_and_enroll(client, ctx, clock)
    r = await client.post("/api/auth/logout")
    assert r.status_code == 403
    r = await client.post("/api/auth/logout", headers={"X-CSRF-Token": "forged"})
    assert r.status_code == 403
    assert (await client.get("/api/system/status")).status_code == 200


async def test_logout_revokes_session(
    client: AsyncClient, ctx: AppContext, clock: FakeClock
) -> None:
    await login_and_enroll(client, ctx, clock)
    token = client.cookies.get("at_session")
    r = await client.post("/api/auth/logout", headers=csrf_headers(client))
    assert r.status_code == 204
    assert (await _get_with_token(client, "/api/system/status", token)).status_code == 401


async def test_idle_timeout(client: AsyncClient, ctx: AppContext, clock: FakeClock) -> None:
    await login_and_enroll(client, ctx, clock)
    idle = timedelta(minutes=ctx.settings.session_idle_timeout_minutes + 1)
    async with ctx.sessionmaker() as db:
        await db.execute(update(UserSession).values(last_seen_at=UserSession.last_seen_at - idle))
        await db.commit()
    assert (await client.get("/api/system/status")).status_code == 401


async def test_pending_session_expires_quickly(client: AsyncClient, ctx: AppContext) -> None:
    await create_owner(ctx)
    await client.post("/api/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
    async with ctx.sessionmaker() as db:
        sess = (await db.execute(select(UserSession))).scalar_one()
        assert sess.expires_at - sess.created_at == timedelta(
            minutes=ctx.settings.mfa_pending_ttl_minutes
        )


async def test_step_up_window(client: AsyncClient, ctx: AppContext, clock: FakeClock) -> None:
    await login_and_enroll(client, ctx, clock)
    async with ctx.sessionmaker() as db:
        sess = (
            (await db.execute(select(UserSession).where(UserSession.revoked_at.is_(None))))
            .scalars()
            .first()
        )
        assert sess is not None
        assert ctx.auth.has_recent_mfa(sess)
        sess.mfa_verified_at -= timedelta(minutes=ctx.settings.step_up_mfa_minutes + 1)
        assert not ctx.auth.has_recent_mfa(sess)


async def test_audit_endpoints(client: AsyncClient, ctx: AppContext, clock: FakeClock) -> None:
    await login_and_enroll(client, ctx, clock)
    r = await client.get("/api/audit")
    assert r.status_code == 200 and r.json()[0]["action"] == "LOGIN_SUCCESS"
    r = await client.get("/api/audit/verify")
    assert r.json()["valid"] is True


async def test_reset_mfa_revokes_sessions(
    client: AsyncClient, ctx: AppContext, clock: FakeClock
) -> None:
    await login_and_enroll(client, ctx, clock)
    async with ctx.sessionmaker() as db:
        await ctx.auth.reset_mfa(db, OWNER_EMAIL)
        await db.commit()
    assert (await client.get("/api/system/status")).status_code == 401
