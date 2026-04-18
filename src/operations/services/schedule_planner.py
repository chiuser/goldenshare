"""Deprecated compatibility shim for src.operations.services.schedule_planner.

Use src.ops.services.schedule_planner instead.
"""

from __future__ import annotations

import sys

from src.ops.services import schedule_planner as _impl

sys.modules[__name__] = _impl
