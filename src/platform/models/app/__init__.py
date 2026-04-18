"""Deprecated compatibility shim.

Use src.app.models instead.
"""

from src.app.models import (
    AppUser,
    AuthActionToken,
    AuthAuditLog,
    AuthInviteCode,
    AuthPermission,
    AuthRefreshToken,
    AuthRole,
    AuthRolePermission,
    AuthUserRole,
)

__all__ = [
    "AppUser",
    "AuthActionToken",
    "AuthAuditLog",
    "AuthInviteCode",
    "AuthPermission",
    "AuthRefreshToken",
    "AuthRole",
    "AuthRolePermission",
    "AuthUserRole",
]
