from __future__ import annotations

# Deprecated compatibility shim:
# platform -> app split phase 1 migrated main implementation to src.app.dependencies.db.
from src.app.dependencies.db import get_db_session


__all__ = ["get_db_session"]
