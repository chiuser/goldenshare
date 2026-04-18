"""Deprecated compatibility shim for src.operations.services.sync_job_state_reconciliation_service.

Use src.ops.services.operations_sync_job_state_reconciliation_service instead.
"""

from __future__ import annotations

import sys

from src.ops.services import operations_sync_job_state_reconciliation_service as _impl

sys.modules[__name__] = _impl
