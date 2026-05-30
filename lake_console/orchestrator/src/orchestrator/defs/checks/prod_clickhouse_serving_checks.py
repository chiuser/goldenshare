from datetime import datetime
from typing import Any

import dagster as dg
from dagster_clickhouse import ClickhouseResource

from orchestrator.defs.assets.clickhouse_serving import (
    CLICKHOUSE_MARKET_BREADTH_TABLE,
    fetch_clickhouse_market_breadth_rows,
    prod_ch_share_fact_market_breadth_daily,
)
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


def _base_metadata(
    *,
    check_scope: CheckScope,
    partition_key: str,
    prod_rows: list[dict[str, Any]] | None = None,
    local_rows: list[dict[str, Any]] | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "partition_key": partition_key,
        "clickhouse_table": CLICKHOUSE_MARKET_BREADTH_TABLE,
    }
    if prod_rows is not None:
        metadata["prod_clickhouse_row_count"] = len(prod_rows)
    if local_rows is not None:
        metadata["local_clickhouse_row_count"] = len(local_rows)
    metadata.update(extra_metadata or {})
    return build_check_metadata(
        check_scope=check_scope,
        extra_metadata=metadata,
    )


def _fetch_rows(
    *,
    partition_key: str,
    clickhouse: ClickhouseResource,
    prod_clickhouse: ClickhouseResource,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with clickhouse.get_connection() as local_client:
        local_rows = fetch_clickhouse_market_breadth_rows(local_client, partition_key)
    with prod_clickhouse.get_connection() as prod_client:
        prod_rows = fetch_clickhouse_market_breadth_rows(prod_client, partition_key)
    return local_rows, prod_rows


def _single_row_failure(
    *,
    partition_key: str,
    local_rows: list[dict[str, Any]],
    prod_rows: list[dict[str, Any]],
    check_scope: CheckScope,
) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=False,
        metadata=_base_metadata(
            check_scope=check_scope,
            partition_key=partition_key,
            local_rows=local_rows,
            prod_rows=prod_rows,
            extra_metadata={
                "expected_local_clickhouse_row_count": 1,
                "expected_prod_clickhouse_row_count": 1,
            },
        ),
    )


@dg.asset_check(asset=prod_ch_share_fact_market_breadth_daily, blocking=True)
def prod_ch_share_fact_market_breadth_row_count_is_one(
    context: dg.AssetCheckExecutionContext,
    prod_clickhouse: ClickhouseResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    with prod_clickhouse.get_connection() as prod_client:
        prod_rows = fetch_clickhouse_market_breadth_rows(prod_client, partition_key)

    return dg.AssetCheckResult(
        passed=len(prod_rows) == 1,
        metadata=_base_metadata(
            check_scope=CheckScope.ROW_COUNT,
            partition_key=partition_key,
            prod_rows=prod_rows,
            extra_metadata={"expected_prod_clickhouse_row_count": 1},
        ),
    )


@dg.asset_check(asset=prod_ch_share_fact_market_breadth_daily, blocking=True)
def prod_ch_share_fact_market_breadth_date_matches_partition(
    context: dg.AssetCheckExecutionContext,
    prod_clickhouse: ClickhouseResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    with prod_clickhouse.get_connection() as prod_client:
        prod_rows = fetch_clickhouse_market_breadth_rows(prod_client, partition_key)

    if len(prod_rows) != 1:
        return dg.AssetCheckResult(
            passed=False,
            metadata=_base_metadata(
                check_scope=CheckScope.PARTITION_ALIGNMENT,
                partition_key=partition_key,
                prod_rows=prod_rows,
                extra_metadata={"expected_prod_clickhouse_row_count": 1},
            ),
        )

    prod_trade_date = prod_rows[0]["trade_date"]
    return dg.AssetCheckResult(
        passed=prod_trade_date == partition_key,
        metadata=_base_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            partition_key=partition_key,
            prod_rows=prod_rows,
            extra_metadata={"prod_clickhouse_trade_date": prod_trade_date},
        ),
    )


@dg.asset_check(asset=prod_ch_share_fact_market_breadth_daily, blocking=True)
def prod_ch_share_fact_market_breadth_row_matches_local(
    context: dg.AssetCheckExecutionContext,
    clickhouse: ClickhouseResource,
    prod_clickhouse: ClickhouseResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    local_rows, prod_rows = _fetch_rows(
        partition_key=partition_key,
        clickhouse=clickhouse,
        prod_clickhouse=prod_clickhouse,
    )
    if len(local_rows) != 1 or len(prod_rows) != 1:
        return _single_row_failure(
            partition_key=partition_key,
            local_rows=local_rows,
            prod_rows=prod_rows,
            check_scope=CheckScope.RECONCILIATION,
        )

    mismatched_fields = [
        field
        for field, local_value in local_rows[0].items()
        if prod_rows[0].get(field) != local_value
    ]
    return dg.AssetCheckResult(
        passed=not mismatched_fields,
        metadata=_base_metadata(
            check_scope=CheckScope.RECONCILIATION,
            partition_key=partition_key,
            local_rows=local_rows,
            prod_rows=prod_rows,
            extra_metadata={
                "mismatched_field_count": len(mismatched_fields),
                "mismatched_field_sample": mismatched_fields[:10],
            },
        ),
    )


@dg.asset_check(asset=prod_ch_share_fact_market_breadth_daily, blocking=True)
def prod_ch_share_fact_market_breadth_updated_at_not_older_than_local(
    context: dg.AssetCheckExecutionContext,
    clickhouse: ClickhouseResource,
    prod_clickhouse: ClickhouseResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    local_rows, prod_rows = _fetch_rows(
        partition_key=partition_key,
        clickhouse=clickhouse,
        prod_clickhouse=prod_clickhouse,
    )
    if len(local_rows) != 1 or len(prod_rows) != 1:
        return _single_row_failure(
            partition_key=partition_key,
            local_rows=local_rows,
            prod_rows=prod_rows,
            check_scope=CheckScope.FRESHNESS,
        )

    local_updated_at = datetime.fromisoformat(local_rows[0]["updated_at"])
    prod_updated_at = datetime.fromisoformat(prod_rows[0]["updated_at"])
    return dg.AssetCheckResult(
        passed=prod_updated_at >= local_updated_at,
        metadata=_base_metadata(
            check_scope=CheckScope.FRESHNESS,
            partition_key=partition_key,
            local_rows=local_rows,
            prod_rows=prod_rows,
            extra_metadata={
                "local_clickhouse_updated_at": local_rows[0]["updated_at"],
                "prod_clickhouse_updated_at": prod_rows[0]["updated_at"],
            },
        ),
    )
