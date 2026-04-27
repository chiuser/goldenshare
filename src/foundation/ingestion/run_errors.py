from __future__ import annotations


class IngestionCanceledError(RuntimeError):
    """Raised when a running ingestion job has received a cancel request."""
