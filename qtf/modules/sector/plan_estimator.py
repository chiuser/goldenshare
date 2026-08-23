from __future__ import annotations

import math


SECTOR_L2_ESTIMATOR_VERSION = "sector_l2_plan_estimator_v1"
SOURCE_STATEMENT_TIMEOUT_MS = 60_000


def estimate_plan_budget(
    *,
    source_rows: int,
    group_days: int,
    valid_object_days: int,
    parameter_combination_count: int,
) -> dict[str, int]:
    """Return deterministic, conservative v1 estimates; these are per-PLAN facts."""
    work_units = source_rows + valid_object_days * parameter_combination_count
    event_upper_bound = valid_object_days * parameter_combination_count
    return {
        "estimatedSourceRows": source_rows,
        "estimatedGroupDays": group_days,
        "parameterCombinationCount": parameter_combination_count,
        "executionPassCount": parameter_combination_count,
        "estimatedSignalEventRows": event_upper_bound,
        "estimatedRuntimeSeconds": max(1, math.ceil(work_units / 50_000)),
        "peakMemoryMb": max(1, math.ceil(source_rows * 512 / (1024 * 1024))),
        "resultStorageMb": max(1, math.ceil(event_upper_bound * 768 / (1024 * 1024))),
        "sourceStatementTimeoutMs": SOURCE_STATEMENT_TIMEOUT_MS,
    }
