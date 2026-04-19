from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_authenticated
from src.app.auth.domain import AuthenticatedUser
from src.app.auth.schemas.auth import (
    CurrentUserResponse,
    LoginRequest,
    LookupAccountRequest,
    LookupAccountResponse,
    LogoutRequest,
    RefreshTokenRequest,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    SessionItem,
    SessionListResponse,
    TokenResponse,
    VerifyActionTokenRequest,
)
from src.app.auth.services.auth_service import AuthService
from src.app.dependencies import get_db_session
from src.app.schemas.common import OkResponse


router = APIRouter(prefix="/auth", tags=["auth"])


def _ip_and_ua(request: Request) -> tuple[str | None, str | None]:
    client_host = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    return client_host, user_agent


@router.post("/register", response_model=RegisterResponse)
def register(body: RegisterRequest, request: Request, session: Session = Depends(get_db_session)) -> RegisterResponse:
    ip_address, user_agent = _ip_and_ua(request)
    service = AuthService()
    user, verify_token_debug, access_token, refresh_token, _ = service.register(
        session,
        username=body.username,
        password=body.password,
        display_name=body.display_name,
        email=body.email,
        invite_code=body.invite_code,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return RegisterResponse(
        user_id=user.id,
        username=user.username,
        account_state=user.account_state,
        requires_email_verification=user.account_state == "pending_verification",
        token=access_token,
        refresh_token=refresh_token,
        verification_token_debug=verify_token_debug if service.should_expose_action_token_debug() else None,
    )


@router.post("/register/resend-verification", response_model=LookupAccountResponse)
def resend_verification(
    body: LookupAccountRequest,
    request: Request,
    session: Session = Depends(get_db_session),
) -> LookupAccountResponse:
    ip_address, user_agent = _ip_and_ua(request)
    service = AuthService()
    debug_token = service.resend_verification(
        session,
        username_or_email=body.username_or_email,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    expose = service.should_expose_action_token_debug()
    return LookupAccountResponse(
        ok=True,
        message="If account exists, a verification instruction has been sent",
        token_debug=debug_token if expose else None,
    )


@router.post("/register/verify", response_model=TokenResponse)
def verify_register_email(
    body: VerifyActionTokenRequest,
    request: Request,
    session: Session = Depends(get_db_session),
) -> TokenResponse:
    ip_address, user_agent = _ip_and_ua(request)
    token, refresh_token, access_expire_at, user = AuthService().verify_email(
        session,
        token=body.token,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return TokenResponse(
        token=token,
        refresh_token=refresh_token,
        access_token_expires_at=access_expire_at,
        username=user.username,
        is_admin=user.is_admin,
        display_name=user.display_name,
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, session: Session = Depends(get_db_session)) -> TokenResponse:
    ip_address, user_agent = _ip_and_ua(request)
    token, refresh_token, access_expire_at, user = AuthService().login(
        session,
        username=body.username,
        password=body.password,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return TokenResponse(
        token=token,
        refresh_token=refresh_token,
        access_token_expires_at=access_expire_at,
        username=user.username,
        is_admin=user.is_admin,
        display_name=user.display_name,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(
    body: RefreshTokenRequest,
    request: Request,
    session: Session = Depends(get_db_session),
) -> TokenResponse:
    ip_address, user_agent = _ip_and_ua(request)
    token, refresh_token, access_expire_at, user = AuthService().refresh(
        session,
        refresh_token=body.refresh_token,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return TokenResponse(
        token=token,
        refresh_token=refresh_token,
        access_token_expires_at=access_expire_at,
        username=user.username,
        is_admin=user.is_admin,
        display_name=user.display_name,
    )


@router.post("/forgot-password", response_model=LookupAccountResponse)
def forgot_password(
    body: LookupAccountRequest,
    request: Request,
    session: Session = Depends(get_db_session),
) -> LookupAccountResponse:
    ip_address, user_agent = _ip_and_ua(request)
    service = AuthService()
    debug_token = service.forgot_password(
        session,
        username_or_email=body.username_or_email,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    expose = service.should_expose_action_token_debug()
    return LookupAccountResponse(
        ok=True,
        message="If account exists, reset instruction has been sent",
        token_debug=debug_token if expose else None,
    )


@router.post("/reset-password", response_model=TokenResponse)
def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    session: Session = Depends(get_db_session),
) -> TokenResponse:
    ip_address, user_agent = _ip_and_ua(request)
    token, refresh_token, access_expire_at, user = AuthService().reset_password(
        session,
        token=body.token,
        new_password=body.new_password,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return TokenResponse(
        token=token,
        refresh_token=refresh_token,
        access_token_expires_at=access_expire_at,
        username=user.username,
        is_admin=user.is_admin,
        display_name=user.display_name,
    )


@router.get("/me", response_model=CurrentUserResponse)
def me(user: AuthenticatedUser = Depends(require_authenticated)) -> CurrentUserResponse:
    payload = asdict(user)
    payload["roles"] = list(user.roles)
    payload["permissions"] = list(user.permissions)
    return CurrentUserResponse(**payload)


@router.get("/sessions", response_model=SessionListResponse)
def list_sessions(user: AuthenticatedUser = Depends(require_authenticated), session: Session = Depends(get_db_session)) -> SessionListResponse:
    rows = AuthService().list_sessions(session, user_id=user.id)
    return SessionListResponse(
        total=len(rows),
        items=[
            SessionItem(
                id=row.id,
                status=row.status,
                issued_at=row.issued_at,
                expires_at=row.expires_at,
                revoked_at=row.revoked_at,
                revoked_reason=row.revoked_reason,
                ip_address=row.ip_address,
                user_agent=row.user_agent,
            )
            for row in rows
        ],
    )


@router.delete("/sessions/{session_id}", response_model=OkResponse)
def revoke_session(
    session_id: int,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
) -> OkResponse:
    AuthService().revoke_session(session, user_id=user.id, session_id=session_id)
    return OkResponse()


@router.post("/logout", response_model=OkResponse)
def logout(
    body: LogoutRequest | None = None,
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
) -> OkResponse:
    AuthService().logout(session, user=user, refresh_token=body.refresh_token if body else None)
    return OkResponse()


@router.post("/logout-all", response_model=OkResponse)
def logout_all(
    user: AuthenticatedUser = Depends(require_authenticated),
    session: Session = Depends(get_db_session),
) -> OkResponse:
    AuthService().logout_all(session, user=user)
    return OkResponse()
