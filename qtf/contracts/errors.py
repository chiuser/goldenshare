from __future__ import annotations


class QtfError(RuntimeError):
    code = "QTF_ERROR"


class QtfRequestInvalid(QtfError):
    code = "QTF_REQUEST_INVALID"


class QtfStateConflict(QtfError):
    code = "QTF_STATE_CONFLICT"


class QtfDraftConflict(QtfStateConflict):
    code = "QTF_DRAFT_CONFLICT"


class QtfRequestConflict(QtfStateConflict):
    """The same idempotency key was reused for different content."""
