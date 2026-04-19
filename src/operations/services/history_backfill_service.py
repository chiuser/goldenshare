"""Deprecated compatibility shim for src.operations.services.history_backfill_service.

Use src.ops.services.operations_history_backfill_service instead.
"""

from __future__ import annotations

import sys

from src.ops.services import operations_history_backfill_service as _impl

sys.modules[__name__] = _impl
