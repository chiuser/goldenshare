from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.platform.auth.domain import AuthenticatedUser
from src.platform.dependencies import get_db_session
from src.platform.exceptions import WebAppError
from src.platform.auth.jwt_service import JWTService
from src.platform.auth.user_repository import UserRepository
from src.platform.web.settings import get_web_settings


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_db_session),
) -> AuthenticatedUser:
    if credentials is None or not credentials.credentials:
        raise WebAppError(status_code=401, code="unauthorized", message="Authentication required")

    jwt_service = JWTService()
    token_payload = jwt_service.decode(credentials.credentials)
    user = UserRepository().get_by_id(session, token_payload.sub)
    if user is None:
        raise WebAppError(status_code=401, code="unauthorized", message="User does not exist")
    if not user.is_active:
        raise WebAppError(status_code=401, code="unauthorized", message="User is inactive")
    return AuthenticatedUser(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        is_admin=user.is_admin,
        is_active=user.is_active,
    )


def require_authenticated(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    return user


def require_admin(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    if not user.is_admin:
        raise WebAppError(status_code=403, code="forbidden", message="Admin permission required")
    return user


def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_db_session),
) -> AuthenticatedUser | None:
    if credentials is None or not credentials.credentials:
        return None

    jwt_service = JWTService()
    token_payload = jwt_service.decode(credentials.credentials)
    user = UserRepository().get_by_id(session, token_payload.sub)
    if user is None:
        raise WebAppError(status_code=401, code="unauthorized", message="User does not exist")
    if not user.is_active:
        raise WebAppError(status_code=401, code="unauthorized", message="User is inactive")
    return AuthenticatedUser(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        is_admin=user.is_admin,
        is_active=user.is_active,
    )


def require_quote_access(
    user: AuthenticatedUser | None = Depends(get_current_user_optional),
) -> AuthenticatedUser | None:
    settings = get_web_settings()
    if settings.quote_api_auth_required and user is None:
        raise WebAppError(status_code=401, code="auth_required", message="当前环境要求登录后访问行情接口")
    return user
