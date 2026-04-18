from __future__ import annotations

# Deprecated compatibility shim:
# platform -> biz split phase 1 migrated main implementation to src.biz.api.share.
from src.biz.api.share import router


__all__ = ["router"]
