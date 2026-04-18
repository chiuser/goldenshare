"""Deprecated compatibility shim.

Use src.app.models.app_user instead.
"""

from src.app.models.app_user import AppUser

__all__ = ["AppUser"]
