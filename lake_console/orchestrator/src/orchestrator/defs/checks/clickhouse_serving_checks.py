from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import dagster as dg
from dagster_clickhouse import ClickhouseResource

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.assets.clickhouse_serving import (
    CLICKHOUSE_MARKET_BREADTH_COLUMNS,
    CLICKHOUSE_MARKET_BREADTH_TABLE,
    ch_share_fact_market_breadth_daily,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.paths import (
    gold_market_breadth_daily_path,
    gold_stock_return_distribution_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


CLICKHOUSE_VALUE_COLUMNS = CLICKHOUSE_MARKET_BREADTH_COLUMNS[:-1]
BREADTH_VALUE_COLUMNS = (
    "up_count",
    "down_count",
    "flat_count",
    "total_count",
    "red_rate",
)
DISTRIBUTION_VALUE_COLUMNS = (
    "down_gt_10_count",
    "down_7_10_count",
    "down_5_7_count",
    "down_3_5_count",
    "down_0_3_count",
    "up_0_3_count",
    "up_3_5_count",
    "up_5_7_count",
    "up_7_10_count",
    "up_gt_10_count",
)


def _date_iso(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _normalise_value(column: str, value: Any) -> Any:
    if column == "trade_date":
        return _date_iso(value)
    if column == "red_rate":
        return float(value)
    return int(value)


def _row_dict(columns: Sequence[str], row: Sequence[Any]) -> dict[str, Any]:
    return {
        column: _normalise_value(column, value)
        for column, value in zip(columns, row, strict=True)
    }


def _fetch_clickhouse_rows(client, partition_key: str) -> list[dict[str, Any]]:
    column_list = ", ".join(CLICKHOUSE_VALUE_COLUMNS)
    rows = client.execute(
        f"""
        SELECT {column_list}
        FROM {CLICKHOUSE_MARKET_BREADTH_TABLE}
        WHERE trade_date = %(trade_date)s
        ORDER BY trade_date
        """,
        {"trade_date": date.fromisoformat(partition_key)},
    )
    return [_row_dict(CLICKHOUSE_VALUE_COLUMNS, row) for row in rows]


def _read_gold_row(
    connection,
    path: Path,
    *,
    columns: Sequence[str],
    dataset_name: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    metadata = {
        f"{dataset_name}_file_path": str(path),
    }
    if not path.exists():
        metadata[f"{dataset_name}_missing_file"] = True
        return None, metadata

    column_list = ", ".join(columns)
    rows = connection.execute(
        f"""
        SELECT {column_list}
        FROM {read_parquet(path, hive_partitioning=False)}
        LIMIT 2
        """
    ).fetchall()
    metadata[f"{dataset_name}_row_count_checked"] = len(rows)
    if len(rows) != 1:
        return None, metadata

    return _row_dict(columns, rows[0]), metadata


def _base_metadata(
    *,
    check_scope: CheckScope,
    partition_key: str,
    clickhouse_rows: Sequence[dict[str, Any]] | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "partition_key": partition_key,
        "clickhouse_table": CLICKHOUSE_MARKET_BREADTH_TABLE,
    }
    if clickhouse_rows is not None:
        metadata["clickhouse_row_count"] = len(clickhouse_rows)
    metadata.update(extra_metadata or {})
    return build_check_metadata(
        check_scope=check_scope,
        extra_metadata=metadata,
    )


def _clickhouse_row_failure_result(
    *,
    partition_key: str,
    clickhouse_rows: Sequence[dict[str, Any]],
    check_scope: CheckScope,
) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=False,
        metadata=_base_metadata(
            check_scope=check_scope,
            partition_key=partition_key,
            clickhouse_rows=clickhouse_rows,
            extra_metadata={
                "expected_clickhouse_row_count": 1,
            },
        ),
    )


def _combined_check_result(
    *,
    rule_results: Sequence[tuple[str, dg.AssetCheckResult]],
    check_scope: CheckScope,
) -> dg.AssetCheckResult:
    failed_rule_names = [
        rule_name for rule_name, result in rule_results if not bool(result.passed)
    ]
    return dg.AssetCheckResult(
        passed=not failed_rule_names,
        metadata=build_check_metadata(
            check_scope=check_scope,
            extra_metadata={
                "summary": (
                    "本机 ClickHouse 市场宽度 serving 聚合检查通过。"
                    if not failed_rule_names
                    else "本机 ClickHouse 市场宽度 serving 聚合检查失败，先看 failed_rule_names。"
                ),
                "next_action": (
                    "无需处理，等待 prod ClickHouse 同步。"
                    if not failed_rule_names
                    else "先修复本机 ClickHouse serving 行数、日期或与 gold 的对账差异，再重跑检查。"
                ),
                "rule_summary": [
                    {"rule_name": rule_name, "passed": bool(result.passed)}
                    for rule_name, result in rule_results
                ],
                "rule_passed": {
                    rule_name: bool(result.passed)
                    for rule_name, result in rule_results
                },
                "failed_rule_names": failed_rule_names,
            },
        ),
    )


def _compare_fields(
    *,
    clickhouse_row: dict[str, Any],
    gold_row: dict[str, Any],
    fields: Sequence[str],
) -> list[dict[str, Any]]:
    mismatches = []
    for field in fields:
        clickhouse_value = clickhouse_row[field]
        gold_value = gold_row[field]
        if field == "red_rate":
            matches = abs(float(clickhouse_value) - float(gold_value)) < 0.000001
        else:
            matches = clickhouse_value == gold_value
        if not matches:
            mismatches.append(
                {
                    "field": field,
                    "clickhouse_value": clickhouse_value,
                    "gold_value": gold_value,
                }
            )
    return mismatches


def ch_share_fact_market_breadth_row_count_is_one(
    context: dg.AssetCheckExecutionContext,
    clickhouse: ClickhouseResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    with clickhouse.get_connection() as client:
        rows = _fetch_clickhouse_rows(client, partition_key)

    return dg.AssetCheckResult(
        passed=len(rows) == 1,
        metadata=_base_metadata(
            check_scope=CheckScope.ROW_COUNT,
            partition_key=partition_key,
            clickhouse_rows=rows,
            extra_metadata={
                "expected_clickhouse_row_count": 1,
            },
        ),
    )


def ch_share_fact_market_breadth_date_matches_partition(
    context: dg.AssetCheckExecutionContext,
    clickhouse: ClickhouseResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    with clickhouse.get_connection() as client:
        rows = _fetch_clickhouse_rows(client, partition_key)
    if len(rows) != 1:
        return _clickhouse_row_failure_result(
            partition_key=partition_key,
            clickhouse_rows=rows,
            check_scope=CheckScope.PARTITION_ALIGNMENT,
        )

    clickhouse_trade_date = rows[0]["trade_date"]
    return dg.AssetCheckResult(
        passed=clickhouse_trade_date == partition_key,
        metadata=_base_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            partition_key=partition_key,
            clickhouse_rows=rows,
            extra_metadata={
                "clickhouse_trade_date": clickhouse_trade_date,
            },
        ),
    )


def ch_share_fact_market_breadth_total_count_matches_gold(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    clickhouse: ClickhouseResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    with clickhouse.get_connection() as client:
        clickhouse_rows = _fetch_clickhouse_rows(client, partition_key)
    if len(clickhouse_rows) != 1:
        return _clickhouse_row_failure_result(
            partition_key=partition_key,
            clickhouse_rows=clickhouse_rows,
            check_scope=CheckScope.RECONCILIATION,
        )

    breadth_path = gold_market_breadth_daily_path(lake_root.root(), partition_key)
    distribution_path = gold_stock_return_distribution_path(
        lake_root.root(),
        partition_key,
    )
    with connect_configured_duckdb() as connection:
        breadth_row, breadth_metadata = _read_gold_row(
            connection,
            breadth_path,
            columns=("trade_date", "total_count"),
            dataset_name="gold_market_breadth_daily",
        )
        distribution_row, distribution_metadata = _read_gold_row(
            connection,
            distribution_path,
            columns=("trade_date", "total_count"),
            dataset_name="gold_stock_return_distribution",
        )

    if breadth_row is None or distribution_row is None:
        return dg.AssetCheckResult(
            passed=False,
            metadata=_base_metadata(
                check_scope=CheckScope.RECONCILIATION,
                partition_key=partition_key,
                clickhouse_rows=clickhouse_rows,
                extra_metadata=breadth_metadata | distribution_metadata,
            ),
        )

    clickhouse_total_count = clickhouse_rows[0]["total_count"]
    breadth_total_count = breadth_row["total_count"]
    distribution_total_count = distribution_row["total_count"]
    return dg.AssetCheckResult(
        passed=clickhouse_total_count
        == breadth_total_count
        == distribution_total_count,
        metadata=_base_metadata(
            check_scope=CheckScope.RECONCILIATION,
            partition_key=partition_key,
            clickhouse_rows=clickhouse_rows,
            extra_metadata={
                **breadth_metadata,
                **distribution_metadata,
                "clickhouse_total_count": clickhouse_total_count,
                "gold_market_breadth_total_count": breadth_total_count,
                "gold_stock_return_distribution_total_count": (
                    distribution_total_count
                ),
            },
        ),
    )


def ch_share_fact_market_breadth_flat_count_matches_gold(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    clickhouse: ClickhouseResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    with clickhouse.get_connection() as client:
        clickhouse_rows = _fetch_clickhouse_rows(client, partition_key)
    if len(clickhouse_rows) != 1:
        return _clickhouse_row_failure_result(
            partition_key=partition_key,
            clickhouse_rows=clickhouse_rows,
            check_scope=CheckScope.RECONCILIATION,
        )

    breadth_path = gold_market_breadth_daily_path(lake_root.root(), partition_key)
    distribution_path = gold_stock_return_distribution_path(
        lake_root.root(),
        partition_key,
    )
    with connect_configured_duckdb() as connection:
        breadth_row, breadth_metadata = _read_gold_row(
            connection,
            breadth_path,
            columns=("trade_date", "flat_count"),
            dataset_name="gold_market_breadth_daily",
        )
        distribution_row, distribution_metadata = _read_gold_row(
            connection,
            distribution_path,
            columns=("trade_date", "flat_count"),
            dataset_name="gold_stock_return_distribution",
        )

    if breadth_row is None or distribution_row is None:
        return dg.AssetCheckResult(
            passed=False,
            metadata=_base_metadata(
                check_scope=CheckScope.RECONCILIATION,
                partition_key=partition_key,
                clickhouse_rows=clickhouse_rows,
                extra_metadata=breadth_metadata | distribution_metadata,
            ),
        )

    clickhouse_flat_count = clickhouse_rows[0]["flat_count"]
    breadth_flat_count = breadth_row["flat_count"]
    distribution_flat_count = distribution_row["flat_count"]
    return dg.AssetCheckResult(
        passed=clickhouse_flat_count == breadth_flat_count == distribution_flat_count,
        metadata=_base_metadata(
            check_scope=CheckScope.RECONCILIATION,
            partition_key=partition_key,
            clickhouse_rows=clickhouse_rows,
            extra_metadata={
                **breadth_metadata,
                **distribution_metadata,
                "clickhouse_flat_count": clickhouse_flat_count,
                "gold_market_breadth_flat_count": breadth_flat_count,
                "gold_stock_return_distribution_flat_count": distribution_flat_count,
            },
        ),
    )


def ch_share_fact_market_breadth_breadth_fields_match_gold(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    clickhouse: ClickhouseResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    with clickhouse.get_connection() as client:
        clickhouse_rows = _fetch_clickhouse_rows(client, partition_key)
    if len(clickhouse_rows) != 1:
        return _clickhouse_row_failure_result(
            partition_key=partition_key,
            clickhouse_rows=clickhouse_rows,
            check_scope=CheckScope.RECONCILIATION,
        )

    breadth_path = gold_market_breadth_daily_path(lake_root.root(), partition_key)
    with connect_configured_duckdb() as connection:
        breadth_row, breadth_metadata = _read_gold_row(
            connection,
            breadth_path,
            columns=("trade_date", *BREADTH_VALUE_COLUMNS),
            dataset_name="gold_market_breadth_daily",
        )
    if breadth_row is None:
        return dg.AssetCheckResult(
            passed=False,
            metadata=_base_metadata(
                check_scope=CheckScope.RECONCILIATION,
                partition_key=partition_key,
                clickhouse_rows=clickhouse_rows,
                extra_metadata=breadth_metadata,
            ),
        )

    mismatches = _compare_fields(
        clickhouse_row=clickhouse_rows[0],
        gold_row=breadth_row,
        fields=BREADTH_VALUE_COLUMNS,
    )
    return dg.AssetCheckResult(
        passed=not mismatches,
        metadata=_base_metadata(
            check_scope=CheckScope.RECONCILIATION,
            partition_key=partition_key,
            clickhouse_rows=clickhouse_rows,
            extra_metadata={
                **breadth_metadata,
                "checked_fields": list(BREADTH_VALUE_COLUMNS),
                "mismatch_count": len(mismatches),
                "mismatch_sample_rows": mismatches[:10],
            },
        ),
    )


def ch_share_fact_market_breadth_distribution_fields_match_gold(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    clickhouse: ClickhouseResource,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    with clickhouse.get_connection() as client:
        clickhouse_rows = _fetch_clickhouse_rows(client, partition_key)
    if len(clickhouse_rows) != 1:
        return _clickhouse_row_failure_result(
            partition_key=partition_key,
            clickhouse_rows=clickhouse_rows,
            check_scope=CheckScope.RECONCILIATION,
        )

    distribution_path = gold_stock_return_distribution_path(
        lake_root.root(),
        partition_key,
    )
    with connect_configured_duckdb() as connection:
        distribution_row, distribution_metadata = _read_gold_row(
            connection,
            distribution_path,
            columns=("trade_date", *DISTRIBUTION_VALUE_COLUMNS),
            dataset_name="gold_stock_return_distribution",
        )
    if distribution_row is None:
        return dg.AssetCheckResult(
            passed=False,
            metadata=_base_metadata(
                check_scope=CheckScope.RECONCILIATION,
                partition_key=partition_key,
                clickhouse_rows=clickhouse_rows,
                extra_metadata=distribution_metadata,
            ),
        )

    mismatches = _compare_fields(
        clickhouse_row=clickhouse_rows[0],
        gold_row=distribution_row,
        fields=DISTRIBUTION_VALUE_COLUMNS,
    )
    return dg.AssetCheckResult(
        passed=not mismatches,
        metadata=_base_metadata(
            check_scope=CheckScope.RECONCILIATION,
            partition_key=partition_key,
            clickhouse_rows=clickhouse_rows,
            extra_metadata={
                **distribution_metadata,
                "checked_fields": list(DISTRIBUTION_VALUE_COLUMNS),
                "mismatch_count": len(mismatches),
                "mismatch_sample_rows": mismatches[:10],
            },
        ),
    )


@dg.asset_check(asset=ch_share_fact_market_breadth_daily, blocking=True)
def ch_share_fact_market_breadth_contract_check(
    context: dg.AssetCheckExecutionContext,
    clickhouse: ClickhouseResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        rule_results=(
            (
                "row_count_is_one",
                ch_share_fact_market_breadth_row_count_is_one(context, clickhouse),
            ),
            (
                "date_matches_partition",
                ch_share_fact_market_breadth_date_matches_partition(
                    context,
                    clickhouse,
                ),
            ),
        ),
        check_scope=CheckScope.ROW_COUNT,
    )


@dg.asset_check(asset=ch_share_fact_market_breadth_daily, blocking=True)
def ch_share_fact_market_breadth_gold_reconciliation_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    clickhouse: ClickhouseResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        rule_results=(
            (
                "total_count_matches_gold",
                ch_share_fact_market_breadth_total_count_matches_gold(
                    context,
                    lake_root,
                    duckdb,
                    clickhouse,
                ),
            ),
            (
                "flat_count_matches_gold",
                ch_share_fact_market_breadth_flat_count_matches_gold(
                    context,
                    lake_root,
                    duckdb,
                    clickhouse,
                ),
            ),
            (
                "breadth_fields_match_gold",
                ch_share_fact_market_breadth_breadth_fields_match_gold(
                    context,
                    lake_root,
                    duckdb,
                    clickhouse,
                ),
            ),
            (
                "distribution_fields_match_gold",
                ch_share_fact_market_breadth_distribution_fields_match_gold(
                    context,
                    lake_root,
                    duckdb,
                    clickhouse,
                ),
            ),
        ),
        check_scope=CheckScope.RECONCILIATION,
    )
