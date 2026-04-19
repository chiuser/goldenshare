"""Deprecated compatibility shim.

Use src.app.models.auth_invite_code instead.
"""

from src.app.models.auth_invite_code import AuthInviteCode

__all__ = ["AuthInviteCode"]
