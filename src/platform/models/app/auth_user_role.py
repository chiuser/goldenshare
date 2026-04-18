"""Deprecated compatibility shim.

Use src.app.models.auth_user_role instead.
"""

from src.app.models.auth_user_role import AuthUserRole

__all__ = ["AuthUserRole"]
