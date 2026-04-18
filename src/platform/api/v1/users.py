from __future__ import annotations

# Deprecated compatibility shim:
# platform -> app/auth split phase 2B migrated main implementation to src.app.auth.api.users.
from src.app.auth.api.users import router


__all__ = ["router"]

