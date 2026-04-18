"""Deprecated compatibility shim for src.operations.services.execution_service.

Use src.ops.services.operations_execution_service instead.
"""

from __future__ import annotations

import sys

from src.ops.services import operations_execution_service as _impl

sys.modules[__name__] = _impl
