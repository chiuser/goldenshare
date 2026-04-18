"""Deprecated compatibility shim for src.operations.services.daily_health_report_service.

Use src.ops.services.operations_daily_health_report_service instead.
"""

from __future__ import annotations

import sys

from src.ops.services import operations_daily_health_report_service as _impl

sys.modules[__name__] = _impl
