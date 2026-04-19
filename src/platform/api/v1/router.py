"""Deprecated compatibility shim.

Use src.app.api.v1.router instead.
"""

from src.app.api.v1.router import router

__all__ = ["router"]
