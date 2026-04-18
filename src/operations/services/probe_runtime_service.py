"""Deprecated compatibility shim for src.operations.services.probe_runtime_service.

Use src.ops.services.operations_probe_runtime_service instead.
"""

from __future__ import annotations

import sys

from src.ops.services import operations_probe_runtime_service as _impl

sys.modules[__name__] = _impl
