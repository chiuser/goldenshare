"""Deprecated compatibility shim.

Use src.app.auth.api.admin_users instead.
"""

from src.app.auth.api.admin_users import router

__all__ = ["router"]
