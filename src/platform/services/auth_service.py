from __future__ import annotations

# Deprecated compatibility shim:
# platform -> app/auth split phase 2B migrated main implementation to src.app.auth.services.auth_service.
from src.app.auth.services.auth_service import AuthService


__all__ = ["AuthService"]

