from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import (
    DB,
    Ctx,
    PendingSession,
    VerifiedSession,
    clear_auth_cookies,
    client_ip,
    csrf_cookie_name,
    require_csrf,
    set_auth_cookies,
)
from app.auth.service import AuthError, RateLimitedError

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class CodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class SessionState(BaseModel):
    email: str
    role: str
    mfa_enrolled: bool
    mfa_verified: bool
    step_up_valid: bool
    session_expires_at: str
    csrf_token: str | None = None


class EnrollmentResponse(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg_data_uri: str


def _auth_error(exc: AuthError) -> HTTPException:
    if isinstance(exc, RateLimitedError):
        return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many attempts; try later")
    return HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc) or "authentication failed")


def _state(ctx: Ctx, sess: PendingSession | VerifiedSession, csrf: str | None) -> SessionState:
    return SessionState(
        email=sess.user.email,
        role=sess.user.role,
        mfa_enrolled=sess.user.mfa_enabled,
        mfa_verified=sess.mfa_verified_at is not None,
        step_up_valid=ctx.auth.has_recent_mfa(sess),
        session_expires_at=sess.expires_at.isoformat(),
        csrf_token=csrf,
    )


@router.post("/login", response_model=SessionState)
async def login(
    body: LoginRequest, request: Request, response: Response, ctx: Ctx, db: DB
) -> SessionState:
    try:
        issued, _user = await ctx.auth.login(
            db, body.email, body.password, client_ip(request), request.headers.get("user-agent")
        )
    except AuthError as exc:
        raise _auth_error(exc) from exc
    csrf = set_auth_cookies(
        response, ctx.settings, issued.token, ctx.settings.mfa_pending_ttl_minutes * 60
    )
    return _state(ctx, issued.session, csrf)


@router.get("/me", response_model=SessionState)
async def me(sess: PendingSession, request: Request, ctx: Ctx) -> SessionState:
    return _state(ctx, sess, request.cookies.get(csrf_cookie_name(ctx.settings)))


@router.post(
    "/mfa/enroll/start", response_model=EnrollmentResponse, dependencies=[Depends(require_csrf)]
)
async def enroll_start(sess: PendingSession, ctx: Ctx, db: DB) -> EnrollmentResponse:
    if sess.mfa_verified_at is not None or sess.user.mfa_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "MFA already enrolled")
    info = await ctx.auth.start_enrollment(db, sess)
    return EnrollmentResponse(
        secret=info.secret, otpauth_uri=info.otpauth_uri, qr_svg_data_uri=info.qr_svg_data_uri
    )


@router.post(
    "/mfa/enroll/confirm", response_model=SessionState, dependencies=[Depends(require_csrf)]
)
async def enroll_confirm(
    body: CodeRequest, sess: PendingSession, request: Request, response: Response, ctx: Ctx, db: DB
) -> SessionState:
    try:
        issued = await ctx.auth.confirm_enrollment(db, sess, body.code, client_ip(request))
    except AuthError as exc:
        raise _auth_error(exc) from exc
    csrf = set_auth_cookies(
        response, ctx.settings, issued.token, ctx.settings.session_absolute_ttl_minutes * 60
    )
    return _state(ctx, issued.session, csrf)


@router.post("/mfa/verify", response_model=SessionState, dependencies=[Depends(require_csrf)])
async def mfa_verify(
    body: CodeRequest, sess: PendingSession, request: Request, response: Response, ctx: Ctx, db: DB
) -> SessionState:
    if sess.mfa_verified_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "session already verified")
    try:
        issued = await ctx.auth.verify_mfa(db, sess, body.code, client_ip(request))
    except AuthError as exc:
        raise _auth_error(exc) from exc
    csrf = set_auth_cookies(
        response, ctx.settings, issued.token, ctx.settings.session_absolute_ttl_minutes * 60
    )
    return _state(ctx, issued.session, csrf)


@router.post("/step-up", response_model=SessionState, dependencies=[Depends(require_csrf)])
async def step_up(
    body: CodeRequest, sess: VerifiedSession, request: Request, ctx: Ctx, db: DB
) -> SessionState:
    try:
        await ctx.auth.step_up(db, sess, body.code, client_ip(request))
    except AuthError as exc:
        raise _auth_error(exc) from exc
    return _state(ctx, sess, request.cookies.get(csrf_cookie_name(ctx.settings)))


@router.post(
    "/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)]
)
async def logout(
    sess: PendingSession, request: Request, response: Response, ctx: Ctx, db: DB
) -> None:
    await ctx.auth.logout(db, sess, client_ip(request))
    clear_auth_cookies(response, ctx.settings)
