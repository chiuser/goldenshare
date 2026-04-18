"""Deprecated compatibility shim.

Use src.app.auth.schemas.user_admin instead.
"""

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

__all__ = [
    "AdminUserListItem",
    "AdminUserListResponse",
    "AdminCreateUserRequest",
    "AdminUpdateUserRequest",
    "AdminSetUserRolesRequest",
    "AdminResetPasswordRequest",
    "AdminInviteCreateRequest",
    "AdminInviteCreateResponse",
    "AdminInviteItem",
    "AdminInviteListResponse",
    "AuthAuditItem",
    "AuthAuditListResponse",
]
