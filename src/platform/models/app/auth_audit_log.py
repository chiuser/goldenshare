"""Deprecated compatibility shim.

Use src.app.models.auth_audit_log instead.
"""

from src.app.models.auth_audit_log import AuthAuditLog

__all__ = ["AuthAuditLog"]
