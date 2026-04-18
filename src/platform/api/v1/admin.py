"""Deprecated compatibility shim.

Use src.app.auth.api.admin instead.
"""

from src.app.auth.api.admin import router

__all__ = ["router"]
