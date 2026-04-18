"""Deprecated compatibility shim for src.operations.services.moneyflow_reconcile_service.

Use src.ops.services.operations_moneyflow_reconcile_service instead.
"""

from __future__ import annotations

import sys

from src.ops.services import operations_moneyflow_reconcile_service as _impl

sys.modules[__name__] = _impl
