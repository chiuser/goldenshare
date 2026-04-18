from __future__ import annotations

# Deprecated compatibility shim:
# platform -> app split phase 1 migrated main implementation to src.app.exceptions.web.
from src.app.exceptions.web import WebAppError, install_exception_handlers


__all__ = ["WebAppError", "install_exception_handlers"]
