from __future__ import annotations

# Deprecated compatibility shim:
# platform -> app/auth split phase 2A migrated main implementation to src.app.auth.jwt_service.
from src.app.auth.jwt_service import JWTService


__all__ = ["JWTService"]
