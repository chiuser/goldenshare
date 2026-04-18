from __future__ import annotations

# Deprecated compatibility shim:
# platform -> app/auth split phase 1 migrated main implementation to src.app.auth.password_service.
from src.app.auth.password_service import PasswordService

__all__ = ["PasswordService"]
