"""Deprecated compatibility shim.

Use src.app.models.auth_refresh_token instead.
"""

from src.app.models.auth_refresh_token import AuthRefreshToken

__all__ = ["AuthRefreshToken"]
