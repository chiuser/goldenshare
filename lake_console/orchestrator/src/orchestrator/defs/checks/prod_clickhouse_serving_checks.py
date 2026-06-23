from datetime import datetime
from typing import Any

import dagster as dg
from dagster_clickhouse import ClickhouseResource

from orchestrator.defs.assets.clickhouse_serving import (
    CLICKHOUSE_MARKET_BREADTH_TABLE,
    PROD_MARKET_BREADTH_SYNC_MAX_PARTITIONS_PER_RUN,
    fetch_clickhouse_market_breadth_rows_for_partitions,
    prod_ch_share_fact_market_breadth_daily,
)
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


FAILURE_SAMPLE_LIMIT = 10


def _selected_partition_keys(context: dg.AssetCheckExecutionContext) -> tuple[str, ...]:
    partition_keys = tuple(sorted(set(context.partition_keys)))
    if not partition_keys:
        raise RuntimeError("prod ClickHouse market breadth check requires partitions.")
    if len(partition_keys) != PROD_MARKET_BREADTH_SYNC_MAX_PARTITIONS_PER_RUN:
        raise RuntimeError(
            "prod ClickHouse market breadth check requires exactly one partition: "
            f"partition_count={len(partition_keys)}, "
            f"required={PROD_MARKET_BREADTH_SYNC_MAX_PARTITIONS_PER_RUN}"
        )
    return partition_keys


def _row_counts_by_partition(
    rows_by_partition: dict[str, list[dict[str, Any]]],
    partition_keys: tuple[str, ...],
) -> dict[str, int]:
    return {
        partition_key: len(rows_by_partition.get(partition_key, []))
        for partition_key in partition_keys
    }


def _row_count_problems(
    rows_by_partition: dict[str, list[dict[str, Any]]],
    partition_keys: tuple[str, ...],
) -> tuple[list[str], list[str]]:
    row_counts = _row_counts_by_partition(rows_by_partition, partition_keys)
    missing_partitions = [
        partition_key for partition_key, row_count in row_counts.items() if row_count == 0
    ]
    duplicate_partitions = [
        partition_key for partition_key, row_count in row_counts.items() if row_count > 1
    ]
    return missing_partitions, duplicate_partitions


def _base_metadata(
    *,
    check_scope: CheckScope,
    partition_keys: tuple[str, ...],
    prod_rows_by_partition: dict[str, list[dict[str, Any]]] | None = None,
    local_rows_by_partition: dict[str, list[dict[str, Any]]] | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    partition_key = partition_keys[0]
    metadata: dict[str, Any] = {
        "partition_key": partition_key,
        "partition_count": 1,
        "clickhouse_table": CLICKHOUSE_MARKET_BREADTH_TABLE,
    }
    if prod_rows_by_partition is not None:
        metadata["prod_clickhouse_row_count"] = sum(
            len(rows) for rows in prod_rows_by_partition.values()
        )
        metadata["prod_clickhouse_row_counts_by_partition"] = _row_counts_by_partition(
            prod_rows_by_partition,
            partition_keys,
        )
    if local_rows_by_partition is not None:
        metadata["local_clickhouse_row_count"] = sum(
            len(rows) for rows in local_rows_by_partition.values()
        )
        metadata["local_clickhouse_row_counts_by_partition"] = _row_counts_by_partition(
            local_rows_by_partition,
            partition_keys,
        )
    metadata.update(extra_metadata or {})
    return build_check_metadata(
        check_scope=check_scope,
        extra_metadata=metadata,
    )


def _fetch_rows(
    *,
    partition_keys: tuple[str, ...],
    clickhouse: ClickhouseResource,
    prod_clickhouse: ClickhouseResource,
) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
]:
    with clickhouse.get_connection() as local_client:
        local_rows_by_partition = fetch_clickhouse_market_breadth_rows_for_partitions(
            local_client,
            partition_keys,
        )
    with prod_clickhouse.get_connection() as prod_client:
        prod_rows_by_partition = fetch_clickhouse_market_breadth_rows_for_partitions(
            prod_client,
            partition_keys,
        )
    return local_rows_by_partition, prod_rows_by_partition


def _single_row_failure(
    *,
    partition_keys: tuple[str, ...],
    local_rows_by_partition: dict[str, list[dict[str, Any]]],
    prod_rows_by_partition: dict[str, list[dict[str, Any]]],
    check_scope: CheckScope,
) -> dg.AssetCheckResult:
    local_missing, local_duplicates = _row_count_problems(
        local_rows_by_partition,
        partition_keys,
    )
    prod_missing, prod_duplicates = _row_count_problems(
        prod_rows_by_partition,
        partition_keys,
    )
    return dg.AssetCheckResult(
        passed=False,
        metadata=_base_metadata(
            check_scope=check_scope,
            partition_keys=partition_keys,
            local_rows_by_partition=local_rows_by_partition,
            prod_rows_by_partition=prod_rows_by_partition,
            extra_metadata={
                "expected_local_clickhouse_row_count_per_partition": 1,
                "expected_prod_clickhouse_row_count_per_partition": 1,
                "local_missing_partition_samples": local_missing[:FAILURE_SAMPLE_LIMIT],
                "local_duplicate_partition_samples": local_duplicates[
                    :FAILURE_SAMPLE_LIMIT
                ],
                "prod_missing_partition_samples": prod_missing[:FAILURE_SAMPLE_LIMIT],
                "prod_duplicate_partition_samples": prod_duplicates[
                    :FAILURE_SAMPLE_LIMIT
                ],
            },
        ),
    )


@dg.asset_check(asset=prod_ch_share_fact_market_breadth_daily, blocking=True)
def prod_ch_share_fact_market_breadth_row_count_is_one(
    context: dg.AssetCheckExecutionContext,
    prod_clickhouse: ClickhouseResource,
) -> dg.AssetCheckResult:
    partition_keys = _selected_partition_keys(context)
    with prod_clickhouse.get_connection() as prod_client:
        prod_rows_by_partition = fetch_clickhouse_market_breadth_rows_for_partitions(
            prod_client,
            partition_keys,
        )

    missing_partitions, duplicate_partitions = _row_count_problems(
        prod_rows_by_partition,
        partition_keys,
    )
    return dg.AssetCheckResult(
        passed=not missing_partitions and not duplicate_partitions,
        metadata=_base_metadata(
            check_scope=CheckScope.ROW_COUNT,
            partition_keys=partition_keys,
            prod_rows_by_partition=prod_rows_by_partition,
            extra_metadata={
                "expected_prod_clickhouse_row_count_per_partition": 1,
                "missing_partition_samples": missing_partitions[:FAILURE_SAMPLE_LIMIT],
                "duplicate_partition_samples": duplicate_partitions[
                    :FAILURE_SAMPLE_LIMIT
                ],
            },
        ),
    )


@dg.asset_check(asset=prod_ch_share_fact_market_breadth_daily, blocking=True)
def prod_ch_share_fact_market_breadth_date_matches_partition(
    context: dg.AssetCheckExecutionContext,
    prod_clickhouse: ClickhouseResource,
) -> dg.AssetCheckResult:
    partition_keys = _selected_partition_keys(context)
    with prod_clickhouse.get_connection() as prod_client:
        prod_rows_by_partition = fetch_clickhouse_market_breadth_rows_for_partitions(
            prod_client,
            partition_keys,
        )

    prod_trade_dates = sorted(
        {
            row["trade_date"]
            for rows in prod_rows_by_partition.values()
            for row in rows
        }
    )
    selected_trade_dates = set(partition_keys)
    missing_partitions = [
        partition_key
        for partition_key in partition_keys
        if partition_key not in prod_trade_dates
    ]
    unexpected_partitions = [
        trade_date for trade_date in prod_trade_dates if trade_date not in selected_trade_dates
    ]
    return dg.AssetCheckResult(
        passed=not missing_partitions and not unexpected_partitions,
        metadata=_base_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            partition_keys=partition_keys,
            prod_rows_by_partition=prod_rows_by_partition,
            extra_metadata={
                "prod_clickhouse_trade_dates": prod_trade_dates,
                "missing_partition_samples": missing_partitions[:FAILURE_SAMPLE_LIMIT],
                "unexpected_partition_samples": unexpected_partitions[
                    :FAILURE_SAMPLE_LIMIT
                ],
            },
        ),
    )


@dg.asset_check(asset=prod_ch_share_fact_market_breadth_daily, blocking=True)
def prod_ch_share_fact_market_breadth_row_matches_local(
    context: dg.AssetCheckExecutionContext,
    clickhouse: ClickhouseResource,
    prod_clickhouse: ClickhouseResource,
) -> dg.AssetCheckResult:
    partition_keys = _selected_partition_keys(context)
    local_rows_by_partition, prod_rows_by_partition = _fetch_rows(
        partition_keys=partition_keys,
        clickhouse=clickhouse,
        prod_clickhouse=prod_clickhouse,
    )
    local_missing, local_duplicates = _row_count_problems(
        local_rows_by_partition,
        partition_keys,
    )
    prod_missing, prod_duplicates = _row_count_problems(
        prod_rows_by_partition,
        partition_keys,
    )
    if local_missing or local_duplicates or prod_missing or prod_duplicates:
        return _single_row_failure(
            partition_keys=partition_keys,
            local_rows_by_partition=local_rows_by_partition,
            prod_rows_by_partition=prod_rows_by_partition,
            check_scope=CheckScope.RECONCILIATION,
        )

    mismatched_partitions: list[dict[str, Any]] = []
    for partition_key in partition_keys:
        local_row = local_rows_by_partition[partition_key][0]
        prod_row = prod_rows_by_partition[partition_key][0]
        mismatched_fields = [
            field
            for field, local_value in local_row.items()
            if prod_row.get(field) != local_value
        ]
        if mismatched_fields:
            mismatched_partitions.append(
                {
                    "partition_key": partition_key,
                    "mismatched_fields": mismatched_fields[:FAILURE_SAMPLE_LIMIT],
                }
            )

    return dg.AssetCheckResult(
        passed=not mismatched_partitions,
        metadata=_base_metadata(
            check_scope=CheckScope.RECONCILIATION,
            partition_keys=partition_keys,
            local_rows_by_partition=local_rows_by_partition,
            prod_rows_by_partition=prod_rows_by_partition,
            extra_metadata={
                "mismatched_field_count": len(
                    mismatched_partitions[0]["mismatched_fields"]
                )
                if mismatched_partitions
                else 0,
                "mismatched_field_samples": (
                    mismatched_partitions[0]["mismatched_fields"][:FAILURE_SAMPLE_LIMIT]
                    if mismatched_partitions
                    else []
                ),
            },
        ),
    )


@dg.asset_check(asset=prod_ch_share_fact_market_breadth_daily, blocking=True)
def prod_ch_share_fact_market_breadth_updated_at_not_older_than_local(
    context: dg.AssetCheckExecutionContext,
    clickhouse: ClickhouseResource,
    prod_clickhouse: ClickhouseResource,
) -> dg.AssetCheckResult:
    partition_keys = _selected_partition_keys(context)
    local_rows_by_partition, prod_rows_by_partition = _fetch_rows(
        partition_keys=partition_keys,
        clickhouse=clickhouse,
        prod_clickhouse=prod_clickhouse,
    )
    local_missing, local_duplicates = _row_count_problems(
        local_rows_by_partition,
        partition_keys,
    )
    prod_missing, prod_duplicates = _row_count_problems(
        prod_rows_by_partition,
        partition_keys,
    )
    if local_missing or local_duplicates or prod_missing or prod_duplicates:
        return _single_row_failure(
            partition_keys=partition_keys,
            local_rows_by_partition=local_rows_by_partition,
            prod_rows_by_partition=prod_rows_by_partition,
            check_scope=CheckScope.FRESHNESS,
        )

    older_prod_partitions: list[dict[str, str]] = []
    for partition_key in partition_keys:
        local_updated_at = datetime.fromisoformat(
            local_rows_by_partition[partition_key][0]["updated_at"]
        )
        prod_updated_at = datetime.fromisoformat(
            prod_rows_by_partition[partition_key][0]["updated_at"]
        )
        if prod_updated_at < local_updated_at:
            older_prod_partitions.append(
                {
                    "partition_key": partition_key,
                    "local_clickhouse_updated_at": local_rows_by_partition[
                        partition_key
                    ][0]["updated_at"],
                    "prod_clickhouse_updated_at": prod_rows_by_partition[
                        partition_key
                    ][0]["updated_at"],
                }
            )

    return dg.AssetCheckResult(
        passed=not older_prod_partitions,
        metadata=_base_metadata(
            check_scope=CheckScope.FRESHNESS,
            partition_keys=partition_keys,
            local_rows_by_partition=local_rows_by_partition,
            prod_rows_by_partition=prod_rows_by_partition,
            extra_metadata={
                "older_prod_partition": bool(older_prod_partitions),
                "older_prod_partition_sample": (
                    older_prod_partitions[0] if older_prod_partitions else {}
                ),
            },
        ),
    )
