"""Deprecated compatibility shim for src.operations.specs.workflow_spec.

Use src.ops.specs.workflow_spec instead.
"""

from __future__ import annotations

import sys

from src.ops.specs import workflow_spec as _impl

sys.modules[__name__] = _impl
