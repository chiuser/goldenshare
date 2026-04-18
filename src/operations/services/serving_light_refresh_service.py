"""Deprecated compatibility shim for src.operations.services.serving_light_refresh_service.

Use src.ops.services.operations_serving_light_refresh_service instead.
"""

from __future__ import annotations

import sys

from src.ops.services import operations_serving_light_refresh_service as _impl

sys.modules[__name__] = _impl
