"""Deprecated compatibility shim.

Use src.app.auth.services.admin_user_service instead.
"""

from src.app.auth.services.admin_user_service import AdminUserService

__all__ = ["AdminUserService"]
