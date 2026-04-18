from __future__ import annotations

# Deprecated compatibility shim:
# platform -> app/auth split phase 1 migrated main implementation to src.app.auth.domain.
from src.app.auth.domain import AuthenticatedUser, TokenPayload

__all__ = ["TokenPayload", "AuthenticatedUser"]
