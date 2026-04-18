"""Deprecated compatibility shim for src.operations.specs.registry.

Use src.ops.specs.registry instead.
"""

from __future__ import annotations

import sys

from src.ops.specs import registry as _impl

sys.modules[__name__] = _impl
