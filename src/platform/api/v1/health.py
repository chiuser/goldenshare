from __future__ import annotations

"""Deprecated compatibility shim.

Use src.app.api.v1.health instead.
"""

from src.app.api.v1.health import build_health_response, health, router

__all__ = ["router", "build_health_response", "health"]
