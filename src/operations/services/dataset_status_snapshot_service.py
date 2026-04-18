"""Deprecated compatibility shim for src.operations.services.dataset_status_snapshot_service.

Use src.ops.services.operations_dataset_status_snapshot_service instead.
"""

from __future__ import annotations

import sys

from src.ops.services import operations_dataset_status_snapshot_service as _impl

sys.modules[__name__] = _impl
