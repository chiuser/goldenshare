from __future__ import annotations

# Deprecated compatibility shim:
# platform -> app/auth split phase 2A migrated main implementation to src.app.auth.dependencies.
from src.app.auth.dependencies import (
    bearer_scheme,
    get_current_user,
    get_current_user_optional,
    require_admin,
    require_authenticated,
    require_permission,
    require_quote_access,
)


__all__ = [
    "bearer_scheme",
    "get_current_user",
    "get_current_user_optional",
    "require_admin",
    "require_authenticated",
    "require_permission",
    "require_quote_access",
]
