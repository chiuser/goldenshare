"""Deprecated compatibility shim for src.operations.services.schedule_probe_binding_service.

Use src.ops.services.schedule_probe_binding_service instead.
"""

from __future__ import annotations

import sys

from src.ops.services import schedule_probe_binding_service as _impl

sys.modules[__name__] = _impl
