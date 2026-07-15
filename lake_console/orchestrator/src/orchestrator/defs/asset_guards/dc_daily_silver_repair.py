"""Silver repair protocol adapter for ``silver_dc_daily``.

This adapter is the source-specific contract entry used by the Silver repair
producer and the Gold repair consumer.  It only builds/parses bounded
in-memory metadata; it does not inspect Dagster event history.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from orchestrator.defs.run_contracts.silver_repair import (
    SilverRepairBatch,
    build_silver_repair_batch,
    parse_silver_repair_batch,
    parse_silver_repair_batch_from_run_tags,
)


DC_DAILY_SILVER_REPAIR_SOURCE_ASSET = "silver_dc_daily"


def build_dc_daily_silver_repair_batch(**kwargs: object) -> SilverRepairBatch:
    """Build the explicit upstream batch consumed by future Gold repair code."""

    return build_silver_repair_batch(
        source_asset=DC_DAILY_SILVER_REPAIR_SOURCE_ASSET,
        **kwargs,
    )


def parse_dc_daily_silver_repair_batch(
    payload: Mapping[str, Any],
    *,
    expected_trade_dates: Sequence[object] | None = None,
    registered_trade_dates: Sequence[object] | None = None,
    max_indicator_recompute_dates: int | None = None,
) -> SilverRepairBatch:
    """Parse and validate a batch while enforcing the Silver source asset."""

    batch = parse_silver_repair_batch(
        payload,
        expected_trade_dates=expected_trade_dates,
        registered_trade_dates=registered_trade_dates,
        max_indicator_recompute_dates=max_indicator_recompute_dates,
    )
    if batch.source_asset != DC_DAILY_SILVER_REPAIR_SOURCE_ASSET:
        raise ValueError(
            "Silver repair batch source_asset must be silver_dc_daily, "
            f"got {batch.source_asset!r}."
        )
    return batch


def parse_dc_daily_silver_repair_batch_from_run_tags(
    tags: Mapping[str, object],
    *,
    expected_trade_dates: Sequence[object] | None = None,
    registered_trade_dates: Sequence[object] | None = None,
    max_indicator_recompute_dates: int | None = None,
) -> SilverRepairBatch:
    """Parse a ready Silver repair batch from scalar producer run tags."""

    batch = parse_silver_repair_batch_from_run_tags(
        tags,
        expected_trade_dates=expected_trade_dates,
        registered_trade_dates=registered_trade_dates,
        max_indicator_recompute_dates=max_indicator_recompute_dates,
    )
    if batch.source_asset != DC_DAILY_SILVER_REPAIR_SOURCE_ASSET:
        raise ValueError(
            "Silver repair batch source_asset must be silver_dc_daily, "
            f"got {batch.source_asset!r}."
        )
    return batch


__all__ = [
    "DC_DAILY_SILVER_REPAIR_SOURCE_ASSET",
    "build_dc_daily_silver_repair_batch",
    "parse_dc_daily_silver_repair_batch",
    "parse_dc_daily_silver_repair_batch_from_run_tags",
]
