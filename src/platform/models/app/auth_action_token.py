"""Deprecated compatibility shim.

Use src.app.models.auth_action_token instead.
"""

from src.app.models.auth_action_token import AuthActionToken

__all__ = ["AuthActionToken"]
