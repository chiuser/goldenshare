from __future__ import annotations

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.auth.domain import AuthenticatedUser
from src.app.auth.jwt_service import JWTService
from src.app.auth.user_repository import UserRepository
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.platform.models.app.auth_role_permission import AuthRolePermission
from src.platform.models.app.auth_user_role import AuthUserRole
from src.platform.web.settings import get_web_settings


bearer_scheme = HTTPBearer(auto_error=False)


def _load_roles_permissions(session: Session, user_id: int, *, is_admin: bool) -> tuple[tuple[str, ...], tuple[str, ...]]:
    role_keys = tuple(
        sorted(
            {
                key
                for key in session.scalars(
                    select(AuthUserRole.role_key).where(AuthUserRole.user_id == user_id)
                ).all()
                if key
            }
        )
    )
    if is_admin and "admin" not in role_keys:
        role_keys = tuple(sorted({*role_keys, "admin"}))
    if not role_keys:
        return role_keys, tuple()
    permission_keys = tuple(
        sorted(
            {
                key
                for key in session.scalars(
                    select(AuthRolePermission.permission_key).where(AuthRolePermission.role_key.in_(role_keys))
                ).all()
                if key
            }
        )
    )
    return role_keys, permission_keys


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
    roles, permissions = _load_roles_permissions(session, user.id, is_admin=user.is_admin)
    return AuthenticatedUser(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        account_state=user.account_state,
        is_admin=user.is_admin,
        is_active=user.is_active,
        roles=roles,
        permissions=permissions,
    )


def require_authenticated(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    return user


def require_admin(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    if not user.is_admin:
        raise WebAppError(status_code=403, code="forbidden", message="Admin permission required")
    return user


def require_permission(permission_key: str):
    def _dependency(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if user.is_admin:
            return user
        if permission_key not in user.permissions:
            raise WebAppError(status_code=403, code="forbidden", message=f"Permission required: {permission_key}")
        return user

    return _dependency


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
    roles, permissions = _load_roles_permissions(session, user.id, is_admin=user.is_admin)
    return AuthenticatedUser(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        account_state=user.account_state,
        is_admin=user.is_admin,
        is_active=user.is_active,
        roles=roles,
        permissions=permissions,
    )


def require_quote_access(
    user: AuthenticatedUser | None = Depends(get_current_user_optional),
) -> AuthenticatedUser | None:
    settings = get_web_settings()
    if settings.quote_api_auth_required and user is None:
        raise WebAppError(status_code=401, code="auth_required", message="当前环境要求登录后访问行情接口")
    return user

