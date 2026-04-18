"""Deprecated compatibility shim for src.operations.runtime.worker.

Use src.ops.runtime.worker instead.
"""

from __future__ import annotations

import sys

from src.ops.runtime import worker as _impl

sys.modules[__name__] = _impl
