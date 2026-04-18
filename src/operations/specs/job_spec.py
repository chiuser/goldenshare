"""Deprecated compatibility shim for src.operations.specs.job_spec.

Use src.ops.specs.job_spec instead.
"""

from __future__ import annotations

import sys

from src.ops.specs import job_spec as _impl

sys.modules[__name__] = _impl
