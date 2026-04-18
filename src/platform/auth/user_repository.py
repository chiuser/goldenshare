from __future__ import annotations

# Deprecated compatibility shim:
# platform -> app/auth split phase 2A migrated main implementation to src.app.auth.user_repository.
from src.app.auth.user_repository import UserRepository


__all__ = ["UserRepository"]
