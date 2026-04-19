from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.app.auth.dependencies import require_permission
from src.app.auth.domain import AuthenticatedUser
from src.app.auth.schemas.user_admin import (
    AdminCreateUserRequest,
    AdminInviteCreateRequest,
    AdminInviteCreateResponse,
    AdminInviteItem,
    AdminInviteListResponse,
    AdminResetPasswordRequest,
    AdminSetUserRolesRequest,
    AdminUpdateUserRequest,
    AdminUserListItem,
    AdminUserListResponse,
    AuthAuditItem,
    AuthAuditListResponse,
)
from src.app.auth.services.admin_user_service import AdminUserService
from src.app.dependencies import get_db_session
from src.app.exceptions import WebAppError
from src.app.schemas.common import OkResponse


router = APIRouter(prefix="/admin", tags=["admin"])


def _serialize_user(item, roles: list[str]) -> AdminUserListItem:  # type: ignore[no-untyped-def]
    return AdminUserListItem(
        id=item.id,
        username=item.username,
        display_name=item.display_name,
        email=item.email,
        account_state=item.account_state,
        is_admin=item.is_admin,
        is_active=item.is_active,
        roles=roles,
        email_verified_at=item.email_verified_at,
        last_login_at=item.last_login_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("/users", response_model=AdminUserListResponse)
def list_users(
    keyword: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: AuthenticatedUser = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> AdminUserListResponse:
    users, role_map, total = AdminUserService().list_users(session, keyword=keyword, limit=limit, offset=offset)
    return AdminUserListResponse(
        total=total,
        items=[_serialize_user(item, role_map.get(item.id, [])) for item in users],
    )


@router.post("/users", response_model=AdminUserListItem)
def create_user(
    body: AdminCreateUserRequest,
    user: AuthenticatedUser = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> AdminUserListItem:
    created = AdminUserService().create_user(
        session,
        username=body.username,
        password=body.password,
        display_name=body.display_name,
        email=body.email,
        is_admin=body.is_admin,
        is_active=body.is_active,
        account_state=body.account_state,
        roles=body.roles,
        actor_user_id=user.id,
    )
    roles_map = AdminUserService().list_users(session, keyword=created.username, limit=1, offset=0)[1]
    return _serialize_user(created, roles_map.get(created.id, []))


@router.patch("/users/{user_id}", response_model=AdminUserListItem)
def update_user(
    user_id: int,
    body: AdminUpdateUserRequest,
    _user: AuthenticatedUser = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> AdminUserListItem:
    updated = AdminUserService().update_user(
        session,
        user_id=user_id,
        display_name=body.display_name,
        email=body.email,
        is_admin=body.is_admin,
        is_active=body.is_active,
        account_state=body.account_state,
    )
    role_map = AdminUserService().list_users(session, keyword=updated.username, limit=1, offset=0)[1]
    return _serialize_user(updated, role_map.get(updated.id, []))


@router.post("/users/{user_id}/roles", response_model=AdminUserListItem)
def replace_user_roles(
    user_id: int,
    body: AdminSetUserRolesRequest,
    user: AuthenticatedUser = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> AdminUserListItem:
    service = AdminUserService()
    role_keys = service.replace_user_roles(
        session,
        user_id=user_id,
        role_keys=body.roles,
        actor_user_id=user.id,
    )
    target = service.user_repository.get_by_id(session, user_id)
    if target is None:
        raise WebAppError(status_code=404, code="not_found", message="User does not exist")
    return _serialize_user(target, role_keys)


@router.post("/users/{user_id}/suspend", response_model=AdminUserListItem)
def suspend_user(
    user_id: int,
    _user: AuthenticatedUser = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> AdminUserListItem:
    item = AdminUserService().suspend_user(session, user_id=user_id)
    role_map = AdminUserService().list_users(session, keyword=item.username, limit=1, offset=0)[1]
    return _serialize_user(item, role_map.get(item.id, []))


@router.post("/users/{user_id}/activate", response_model=AdminUserListItem)
def activate_user(
    user_id: int,
    _user: AuthenticatedUser = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> AdminUserListItem:
    item = AdminUserService().activate_user(session, user_id=user_id)
    role_map = AdminUserService().list_users(session, keyword=item.username, limit=1, offset=0)[1]
    return _serialize_user(item, role_map.get(item.id, []))


@router.post("/users/{user_id}/reset-password", response_model=OkResponse)
def admin_reset_password(
    user_id: int,
    body: AdminResetPasswordRequest,
    _user: AuthenticatedUser = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> OkResponse:
    AdminUserService().admin_reset_password(session, user_id=user_id, password=body.password)
    return OkResponse()


@router.delete("/users/{user_id}", response_model=OkResponse)
def delete_user(
    user_id: int,
    user: AuthenticatedUser = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> OkResponse:
    AdminUserService().delete_user(session, user_id=user_id, actor_user_id=user.id)
    return OkResponse()


@router.get("/auth-audit", response_model=AuthAuditListResponse)
def list_auth_audit(
    user_id: int | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _user: AuthenticatedUser = Depends(require_permission("auth.audit.read")),
    session: Session = Depends(get_db_session),
) -> AuthAuditListResponse:
    rows, total = AdminUserService().list_auth_audit(
        session,
        user_id=user_id,
        event_type=event_type,
        limit=limit,
        offset=offset,
    )
    return AuthAuditListResponse(
        total=total,
        items=[
            AuthAuditItem(
                id=item.id,
                user_id=item.user_id,
                username_snapshot=item.username_snapshot,
                event_type=item.event_type,
                event_status=item.event_status,
                ip_address=item.ip_address,
                user_agent=item.user_agent,
                detail_json=item.detail_json,
                occurred_at=item.occurred_at,
            )
            for item in rows
        ],
    )


@router.post("/invites", response_model=AdminInviteCreateResponse)
def create_invite(
    body: AdminInviteCreateRequest,
    user: AuthenticatedUser = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> AdminInviteCreateResponse:
    row, raw_code = AdminUserService().create_invite(
        session,
        role_key=body.role_key,
        assigned_email=body.assigned_email,
        max_uses=body.max_uses,
        expires_at=body.expires_at,
        note=body.note,
        actor_user_id=user.id,
        code=body.code,
    )
    return AdminInviteCreateResponse(
        id=row.id,
        code=raw_code,
        role_key=row.role_key,
        assigned_email=row.assigned_email,
        max_uses=row.max_uses,
        used_count=row.used_count,
        expires_at=row.expires_at,
        disabled_at=row.disabled_at,
        note=row.note,
        created_at=row.created_at,
    )


@router.get("/invites", response_model=AdminInviteListResponse)
def list_invites(
    include_disabled: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _user: AuthenticatedUser = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> AdminInviteListResponse:
    rows, total = AdminUserService().list_invites(
        session,
        include_disabled=include_disabled,
        limit=limit,
        offset=offset,
    )
    return AdminInviteListResponse(
        total=total,
        items=[
            AdminInviteItem(
                id=item.id,
                code_hint=item.code_hint,
                role_key=item.role_key,
                assigned_email=item.assigned_email,
                max_uses=item.max_uses,
                used_count=item.used_count,
                expires_at=item.expires_at,
                disabled_at=item.disabled_at,
                last_used_at=item.last_used_at,
                created_by_user_id=item.created_by_user_id,
                note=item.note,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in rows
        ],
    )


@router.delete("/invites/{invite_id}", response_model=OkResponse)
def disable_invite(
    invite_id: int,
    user: AuthenticatedUser = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> OkResponse:
    AdminUserService().disable_invite(session, invite_id=invite_id, actor_user_id=user.id)
    return OkResponse()


@router.delete("/invites/{invite_id}/hard-delete", response_model=OkResponse)
def delete_invite(
    invite_id: int,
    user: AuthenticatedUser = Depends(require_permission("user.manage")),
    session: Session = Depends(get_db_session),
) -> OkResponse:
    AdminUserService().delete_invite(session, invite_id=invite_id, actor_user_id=user.id)
    return OkResponse()
