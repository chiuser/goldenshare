from __future__ import annotations


class ExecutionCanceledError(RuntimeError):
    """Raised when a running execution has received a cancel request."""

