"""Deprecated compatibility shim.

Use src.app.models.auth_permission instead.
"""

from src.app.models.auth_permission import AuthPermission

__all__ = ["AuthPermission"]
