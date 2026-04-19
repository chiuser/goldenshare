"""Deprecated compatibility shim.

Use src.app.models instead.
"""

from importlib import import_module
from typing import Any


_EXPORT_TO_MODULE: dict[str, str] = {
    "AppUser": "src.app.models.app_user",
    "AuthActionToken": "src.app.models.auth_action_token",
    "AuthAuditLog": "src.app.models.auth_audit_log",
    "AuthInviteCode": "src.app.models.auth_invite_code",
    "AuthPermission": "src.app.models.auth_permission",
    "AuthRefreshToken": "src.app.models.auth_refresh_token",
    "AuthRole": "src.app.models.auth_role",
    "AuthRolePermission": "src.app.models.auth_role_permission",
    "AuthUserRole": "src.app.models.auth_user_role",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value

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
