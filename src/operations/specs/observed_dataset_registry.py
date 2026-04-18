"""Deprecated compatibility shim for src.operations.specs.observed_dataset_registry.

Use src.ops.specs.observed_dataset_registry instead.
"""

from __future__ import annotations

import sys

from src.ops.specs import observed_dataset_registry as _impl

sys.modules[__name__] = _impl
