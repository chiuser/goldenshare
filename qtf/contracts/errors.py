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


class QtfTemplateNotFound(QtfError):
    code = "QTF_TEMPLATE_NOT_FOUND"


class QtfInputPreflightBlocked(QtfError):
    code = "QTF_INPUT_PREFLIGHT_BLOCKED"


class QtfPlanNotApproved(QtfStateConflict):
    code = "QTF_PLAN_NOT_APPROVED"


class QtfPlanBudgetExceeded(QtfStateConflict):
    code = "QTF_PLAN_BUDGET_EXCEEDED"


class QtfInputChangedDuringRun(QtfStateConflict):
    code = "QTF_INPUT_CHANGED_DURING_RUN"


class QtfRunFailed(QtfError):
    code = "QTF_RUN_FAILED"


class QtfQueryFailed(QtfError):
    code = "QTF_QUERY_FAILED"
