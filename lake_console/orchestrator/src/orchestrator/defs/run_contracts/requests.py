"""RunRequest builders that avoid custom run tag drift."""

from collections.abc import Mapping
from typing import Any

import dagster as dg


def build_run_request(
    *,
    run_key: str,
    partition_key: str | None = None,
    run_config: Mapping[str, Any] | None = None,
) -> dg.RunRequest:
    """Build a Dagster RunRequest without project-defined run tags."""

    return dg.RunRequest(
        run_key=run_key,
        partition_key=partition_key,
        run_config=dict(run_config) if run_config else None,
    )
