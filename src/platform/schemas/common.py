"""Deprecated compatibility shim.

Use src.app.schemas.common instead.
"""

from src.app.schemas.common import ApiErrorResponse, HealthResponse, OkResponse

__all__ = ["ApiErrorResponse", "HealthResponse", "OkResponse"]
