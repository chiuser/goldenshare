"""Deprecated compatibility shim.

Use src.app.models.auth_role_permission instead.
"""

from src.app.models.auth_role_permission import AuthRolePermission

__all__ = ["AuthRolePermission"]
