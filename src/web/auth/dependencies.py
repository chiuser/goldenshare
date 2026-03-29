from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.web.dependencies import get_db_session
from src.web.domain.user import AuthenticatedUser
from src.web.exceptions import WebAppError
from src.web.auth.jwt_service import JWTService
from src.web.repositories.user_repository import UserRepository


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
