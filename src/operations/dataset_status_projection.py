"""Deprecated compatibility shim for src.operations.dataset_status_projection.

Use src.ops.dataset_status_projection instead.
"""

from __future__ import annotations

import sys

from src.ops import dataset_status_projection as _impl

sys.modules[__name__] = _impl
