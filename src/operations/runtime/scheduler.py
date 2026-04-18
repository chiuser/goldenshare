"""Deprecated compatibility shim for src.operations.runtime.scheduler.

Use src.ops.runtime.scheduler instead.
"""

from __future__ import annotations

import sys

from src.ops.runtime import scheduler as _impl

sys.modules[__name__] = _impl
