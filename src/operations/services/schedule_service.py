"""Deprecated compatibility shim for src.operations.services.schedule_service.

Use src.ops.services.operations_schedule_service instead.
"""

from __future__ import annotations

import sys

from src.ops.services import operations_schedule_service as _impl

sys.modules[__name__] = _impl
