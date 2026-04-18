"""Deprecated compatibility shim.

Use src.app.models.auth_role instead.
"""

from src.app.models.auth_role import AuthRole

__all__ = ["AuthRole"]
