"""Deprecated compatibility shim for src.operations.runtime.dispatcher.

Use src.ops.runtime.dispatcher instead.
"""

from __future__ import annotations

import sys

from src.ops.runtime import dispatcher as _impl

sys.modules[__name__] = _impl
