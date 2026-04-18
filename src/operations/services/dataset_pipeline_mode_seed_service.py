"""Deprecated compatibility shim for src.operations.services.dataset_pipeline_mode_seed_service.

Use src.ops.services.operations_dataset_pipeline_mode_seed_service instead.
"""

from __future__ import annotations

import sys

from src.ops.services import operations_dataset_pipeline_mode_seed_service as _impl

sys.modules[__name__] = _impl
