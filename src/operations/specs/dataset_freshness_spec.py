"""Deprecated compatibility shim for src.operations.specs.dataset_freshness_spec.

Use src.ops.specs.dataset_freshness_spec instead.
"""

from __future__ import annotations

import sys

from src.ops.specs import dataset_freshness_spec as _impl

sys.modules[__name__] = _impl
