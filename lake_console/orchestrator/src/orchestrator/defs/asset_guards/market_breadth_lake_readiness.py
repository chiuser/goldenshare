"""Lake and ClickHouse readiness for market breadth continuity sensors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from time import perf_counter
from typing import Any

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
)
from orchestrator.defs.assets.clickhouse_serving import (
    CLICKHOUSE_MARKET_BREADTH_COLUMNS,
    fetch_clickhouse_market_breadth_rows_for_partitions,
)
from orchestrator.defs.duckdb_sql import (
    count_parquet_query,
    describe_parquet_query,
    market_breadth_daily_select,
    read_parquet,
    stock_return_distribution_select,
)
from orchestrator.defs.paths import (
    gold_market_breadth_daily_path,
    gold_stock_return_distribution_path,
    silver_stock_daily_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_MARKET_BREADTH_DAILY_SCHEMA,
    GOLD_STOCK_RETURN_DISTRIBUTION_SCHEMA,
)


GOLD_MARKET_BREADTH_LAKE_CHECK_NAMES = (
    "gold_market_breadth_row_count_is_one",
    "gold_market_breadth_counts_add_up",
    "gold_market_breadth_total_count_positive",
    "gold_market_breadth_total_count_matches_silver",
    "gold_market_breadth_red_rate_range",
    "gold_market_breadth_red_rate_formula",
    "gold_market_breadth_matches_silver_recompute",
    "gold_market_breadth_stock_partition_key_allowed",
)
GOLD_STOCK_RETURN_DISTRIBUTION_LAKE_CHECK_NAMES = (
    "gold_stock_return_distribution_row_count_is_one",
    "gold_stock_return_distribution_counts_add_up",
    "gold_stock_return_distribution_total_count_matches_silver",
    "gold_stock_return_distribution_partition_date_matches",
    "gold_stock_return_distribution_recomputed_from_silver",
    "gold_stock_return_distribution_stock_partition_key_allowed",
)
CH_SHARE_FACT_MARKET_BREADTH_LAKE_CHECK_NAMES = (
    "ch_share_fact_market_breadth_row_count_is_one",
    "ch_share_fact_market_breadth_date_matches_partition",
    "ch_share_fact_market_breadth_total_count_matches_gold",
    "ch_share_fact_market_breadth_flat_count_matches_gold",
    "ch_share_fact_market_breadth_breadth_fields_match_gold",
    "ch_share_fact_market_breadth_distribution_fields_match_gold",
)
PROD_CH_SHARE_FACT_MARKET_BREADTH_LAKE_CHECK_NAMES = (
    "prod_ch_share_fact_market_breadth_row_count_is_one",
    "prod_ch_share_fact_market_breadth_date_matches_partition",
    "prod_ch_share_fact_market_breadth_row_matches_local",
    "prod_ch_share_fact_market_breadth_updated_at_not_older_than_local",
)

_GOLD_BREADTH_REQUIRED_COLUMNS = tuple(
    column.name for column in GOLD_MARKET_BREADTH_DAILY_SCHEMA
)
_GOLD_BREADTH_COLUMN_TYPES = {
    column.name: column.type.upper() for column in GOLD_MARKET_BREADTH_DAILY_SCHEMA
}
_GOLD_DISTRIBUTION_REQUIRED_COLUMNS = tuple(
    column.name for column in GOLD_STOCK_RETURN_DISTRIBUTION_SCHEMA
)
_GOLD_DISTRIBUTION_COLUMN_TYPES = {
    column.name: column.type.upper()
    for column in GOLD_STOCK_RETURN_DISTRIBUTION_SCHEMA
}
_BREADTH_VALUE_COLUMNS = (
    "up_count",
    "down_count",
    "flat_count",
    "total_count",
    "red_rate",
)
_DISTRIBUTION_VALUE_COLUMNS = (
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
_CLICKHOUSE_VALUE_COLUMNS = CLICKHOUSE_MARKET_BREADTH_COLUMNS[:-1]


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)


def _missing_file_status(
    *,
    trade_date: str,
    check_name: str,
    file_path: Path,
    reason: str,
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=False,
        checks_passed=False,
        reason=reason,
        missing_check_names=(check_name,),
        missing_file_paths=(str(file_path),),
        summary={"file_path": str(file_path)},
    )


def _failed_status(
    *,
    trade_date: str,
    reason: str,
    failed_check_names: Sequence[str],
    summary: Mapping[str, object],
    missing_file_paths: Sequence[str] = (),
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=True,
        checks_passed=False,
        reason=reason,
        failed_check_names=tuple(dict.fromkeys(failed_check_names)),
        missing_file_paths=tuple(missing_file_paths),
        summary=dict(summary),
    )


def _ready_status(
    *,
    trade_date: str,
    summary: Mapping[str, object],
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=True,
        materialized=True,
        checks_passed=True,
        reason="ready",
        summary=dict(summary),
    )


def _scan_error_status(
    *,
    trade_date: str,
    materialized: bool,
    error: Exception,
    file_path: Path | None = None,
) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=materialized,
        checks_passed=False,
        reason="scan_error",
        failed_check_names=("lake_readiness_scan_error",),
        missing_file_paths=()
        if file_path is None or materialized
        else (str(file_path),),
        summary={
            "scan_error_code": type(error).__name__,
            "scan_error": str(error),
        },
    )


def _schema_failures(
    connection,
    path: Path,
    *,
    required_columns: Sequence[str],
    expected_types: Mapping[str, str],
) -> dict[str, object]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=False)
    ).fetchall()
    columns = [str(row[0]) for row in rows]
    column_types = {str(row[0]): str(row[1]).upper() for row in rows}
    missing_columns = [column for column in required_columns if column not in columns]
    unexpected_columns = [
        column for column in columns if column not in set(required_columns)
    ]
    type_mismatches = {
        column: {
            "expected": expected_type,
            "actual": column_types.get(column),
        }
        for column, expected_type in expected_types.items()
        if column in column_types and column_types[column] != expected_type
    }
    return {
        "observed_columns": columns,
        "missing_columns": missing_columns,
        "unexpected_columns": unexpected_columns,
        "type_mismatches": type_mismatches,
    }


def _schema_failed(schema_result: Mapping[str, object]) -> bool:
    return bool(
        schema_result["missing_columns"]
        or schema_result["unexpected_columns"]
        or schema_result["type_mismatches"]
    )


def _one_row_count(connection, path: Path) -> int:
    return int(
        connection.execute(
            count_parquet_query(path, hive_partitioning=False)
        ).fetchone()[0]
    )


def _single_row_dict(
    connection,
    path: Path,
    *,
    columns: Sequence[str],
) -> dict[str, Any] | None:
    rows = connection.execute(
        f"""
        SELECT {", ".join(columns)}
        FROM {read_parquet(path, hive_partitioning=False)}
        LIMIT 2
        """
    ).fetchall()
    if len(rows) != 1:
        return None
    return {
        column: _normalise_value(column, value)
        for column, value in zip(columns, rows[0], strict=True)
    }


def _normalise_value(column: str, value: Any) -> Any:
    if column == "trade_date":
        return value.isoformat() if hasattr(value, "isoformat") else str(value)
    if column in {"red_rate"}:
        return float(value)
    if column == "updated_at":
        if hasattr(value, "isoformat"):
            return value.isoformat(sep=" ")
        return str(value)
    return int(value)


def _read_recomputed_breadth_row(
    connection,
    *,
    silver_path: Path,
    trade_date: str,
) -> dict[str, Any] | None:
    row = connection.execute(market_breadth_daily_select(silver_path, trade_date)).fetchone()
    if row is None:
        return None
    return {
        "trade_date": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
        "up_count": int(row[1]),
        "down_count": int(row[2]),
        "flat_count": int(row[3]),
        "total_count": int(row[4]),
        "red_rate": float(row[5]),
    }


def _read_recomputed_distribution_row(
    connection,
    *,
    silver_path: Path,
    trade_date: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        stock_return_distribution_select(silver_path, trade_date)
    ).fetchone()
    if row is None:
        return None
    result: dict[str, Any] = {
        "trade_date": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
    }
    for column, value in zip(_GOLD_DISTRIBUTION_REQUIRED_COLUMNS[1:], row[1:], strict=True):
        result[column] = int(value)
    return result


def _gold_breadth_status(
    *,
    connection,
    lake_root_path: Path,
    trade_date: str,
) -> ContinuityDateReadiness:
    path = gold_market_breadth_daily_path(lake_root_path, trade_date)
    if not path.exists():
        return _missing_file_status(
            trade_date=trade_date,
            check_name="gold_market_breadth_row_count_is_one",
            file_path=path,
            reason="missing_gold_market_breadth_file",
        )

    try:
        failed: list[str] = []
        missing_paths: list[str] = []
        summary: dict[str, object] = {"file_path": str(path)}
        schema_result = _schema_failures(
            connection,
            path,
            required_columns=_GOLD_BREADTH_REQUIRED_COLUMNS,
            expected_types=_GOLD_BREADTH_COLUMN_TYPES,
        )
        if _schema_failed(schema_result):
            failed.append("gold_market_breadth_required_columns_and_types")
            summary["schema"] = schema_result

        row_count = _one_row_count(connection, path)
        summary["row_count"] = row_count
        if row_count != 1:
            failed.append("gold_market_breadth_row_count_is_one")

        gold_row = _single_row_dict(
            connection,
            path,
            columns=_GOLD_BREADTH_REQUIRED_COLUMNS,
        )
        if gold_row is not None:
            summary["gold_row"] = gold_row
            if (
                int(gold_row["up_count"])
                + int(gold_row["down_count"])
                + int(gold_row["flat_count"])
                != int(gold_row["total_count"])
            ):
                failed.append("gold_market_breadth_counts_add_up")
            if int(gold_row["total_count"]) <= 0:
                failed.append("gold_market_breadth_total_count_positive")
            red_rate = float(gold_row["red_rate"])
            if red_rate < 0 or red_rate > 100:
                failed.append("gold_market_breadth_red_rate_range")
            expected_red_rate = (
                0.0
                if int(gold_row["total_count"]) == 0
                else round(int(gold_row["up_count"]) * 100.0 / int(gold_row["total_count"]), 2)
            )
            summary["expected_red_rate"] = expected_red_rate
            if abs(red_rate - expected_red_rate) > 0.000001:
                failed.append("gold_market_breadth_red_rate_formula")

        silver_path = silver_stock_daily_path(lake_root_path, trade_date)
        if not silver_path.exists():
            failed.extend(
                [
                    "gold_market_breadth_total_count_matches_silver",
                    "gold_market_breadth_matches_silver_recompute",
                ]
            )
            missing_paths.append(str(silver_path))
            summary["silver_file_path"] = str(silver_path)
            summary["missing_silver_file"] = True
        else:
            silver_row_count = _one_row_count(connection, silver_path)
            summary["silver_row_count"] = silver_row_count
            if gold_row is not None and int(gold_row["total_count"]) != silver_row_count:
                failed.append("gold_market_breadth_total_count_matches_silver")
            recomputed_row = _read_recomputed_breadth_row(
                connection,
                silver_path=silver_path,
                trade_date=trade_date,
            )
            summary["recomputed_row"] = recomputed_row or {}
            if gold_row != recomputed_row:
                failed.append("gold_market_breadth_matches_silver_recompute")

        if failed:
            return _failed_status(
                trade_date=trade_date,
                reason="blocking_checks_failed",
                failed_check_names=failed,
                missing_file_paths=missing_paths,
                summary=summary,
            )
        return _ready_status(trade_date=trade_date, summary=summary)
    except Exception as error:
        return _scan_error_status(
            trade_date=trade_date,
            materialized=True,
            error=error,
            file_path=path,
        )


def _gold_distribution_status(
    *,
    connection,
    lake_root_path: Path,
    trade_date: str,
) -> ContinuityDateReadiness:
    path = gold_stock_return_distribution_path(lake_root_path, trade_date)
    if not path.exists():
        return _missing_file_status(
            trade_date=trade_date,
            check_name="gold_stock_return_distribution_row_count_is_one",
            file_path=path,
            reason="missing_gold_stock_return_distribution_file",
        )

    try:
        failed: list[str] = []
        missing_paths: list[str] = []
        summary: dict[str, object] = {"file_path": str(path)}
        schema_result = _schema_failures(
            connection,
            path,
            required_columns=_GOLD_DISTRIBUTION_REQUIRED_COLUMNS,
            expected_types=_GOLD_DISTRIBUTION_COLUMN_TYPES,
        )
        if _schema_failed(schema_result):
            failed.append("gold_stock_return_distribution_required_columns_and_types")
            summary["schema"] = schema_result

        row_count = _one_row_count(connection, path)
        summary["row_count"] = row_count
        if row_count != 1:
            failed.append("gold_stock_return_distribution_row_count_is_one")

        gold_row = _single_row_dict(
            connection,
            path,
            columns=_GOLD_DISTRIBUTION_REQUIRED_COLUMNS,
        )
        if gold_row is not None:
            summary["gold_row"] = gold_row
            bucket_sum = sum(
                int(gold_row[column])
                for column in _GOLD_DISTRIBUTION_REQUIRED_COLUMNS[1:-1]
            )
            summary["bucket_sum"] = bucket_sum
            if bucket_sum != int(gold_row["total_count"]):
                failed.append("gold_stock_return_distribution_counts_add_up")
            if gold_row["trade_date"] != trade_date:
                failed.append("gold_stock_return_distribution_partition_date_matches")

        silver_path = silver_stock_daily_path(lake_root_path, trade_date)
        if not silver_path.exists():
            failed.extend(
                [
                    "gold_stock_return_distribution_total_count_matches_silver",
                    "gold_stock_return_distribution_recomputed_from_silver",
                ]
            )
            missing_paths.append(str(silver_path))
            summary["silver_file_path"] = str(silver_path)
            summary["missing_silver_file"] = True
        else:
            silver_row_count = _one_row_count(connection, silver_path)
            summary["silver_row_count"] = silver_row_count
            if gold_row is not None and int(gold_row["total_count"]) != silver_row_count:
                failed.append("gold_stock_return_distribution_total_count_matches_silver")
            recomputed_row = _read_recomputed_distribution_row(
                connection,
                silver_path=silver_path,
                trade_date=trade_date,
            )
            summary["recomputed_row"] = recomputed_row or {}
            if gold_row != recomputed_row:
                failed.append("gold_stock_return_distribution_recomputed_from_silver")

        if failed:
            return _failed_status(
                trade_date=trade_date,
                reason="blocking_checks_failed",
                failed_check_names=failed,
                missing_file_paths=missing_paths,
                summary=summary,
            )
        return _ready_status(trade_date=trade_date, summary=summary)
    except Exception as error:
        return _scan_error_status(
            trade_date=trade_date,
            materialized=True,
            error=error,
            file_path=path,
        )


def _batch_from_status_factory(
    *,
    expected_trade_dates: Sequence[str],
    status_factory,
    scanned_file_count: int,
) -> ContinuityBatchReadiness:
    started_at = perf_counter()
    expected_trade_dates = tuple(str(value) for value in expected_trade_dates)
    statuses = {
        trade_date: status_factory(trade_date)
        for trade_date in expected_trade_dates
    }
    return ContinuityBatchReadiness(
        expected_trade_dates=expected_trade_dates,
        statuses_by_trade_date=statuses,
        elapsed_ms=_elapsed_ms(started_at),
        scanned_file_count=scanned_file_count,
    )


def batch_gold_market_breadth_lake_readiness(
    *,
    connection,
    lake_root_path: Path,
    expected_trade_dates: Sequence[str],
) -> ContinuityBatchReadiness:
    expected_trade_dates = tuple(str(value) for value in expected_trade_dates)
    existing_count = sum(
        1
        for trade_date in expected_trade_dates
        if gold_market_breadth_daily_path(lake_root_path, trade_date).exists()
    )
    return _batch_from_status_factory(
        expected_trade_dates=expected_trade_dates,
        status_factory=lambda trade_date: _gold_breadth_status(
            connection=connection,
            lake_root_path=lake_root_path,
            trade_date=trade_date,
        ),
        scanned_file_count=existing_count,
    )


def batch_gold_stock_return_distribution_lake_readiness(
    *,
    connection,
    lake_root_path: Path,
    expected_trade_dates: Sequence[str],
) -> ContinuityBatchReadiness:
    expected_trade_dates = tuple(str(value) for value in expected_trade_dates)
    existing_count = sum(
        1
        for trade_date in expected_trade_dates
        if gold_stock_return_distribution_path(lake_root_path, trade_date).exists()
    )
    return _batch_from_status_factory(
        expected_trade_dates=expected_trade_dates,
        status_factory=lambda trade_date: _gold_distribution_status(
            connection=connection,
            lake_root_path=lake_root_path,
            trade_date=trade_date,
        ),
        scanned_file_count=existing_count,
    )


def _clickhouse_summary_rows(
    rows_by_partition: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, int]:
    return {
        partition_key: len(rows)
        for partition_key, rows in rows_by_partition.items()
    }


def _single_clickhouse_row(
    rows_by_partition: Mapping[str, Sequence[Mapping[str, Any]]],
    trade_date: str,
) -> Mapping[str, Any] | None:
    rows = rows_by_partition.get(trade_date, ())
    if len(rows) != 1:
        return None
    return rows[0]


def _expected_clickhouse_row(
    *,
    connection,
    lake_root_path: Path,
    trade_date: str,
) -> tuple[dict[str, Any] | None, dict[str, object], list[str]]:
    missing_paths: list[str] = []
    summary: dict[str, object] = {}
    breadth_path = gold_market_breadth_daily_path(lake_root_path, trade_date)
    distribution_path = gold_stock_return_distribution_path(lake_root_path, trade_date)
    if not breadth_path.exists():
        missing_paths.append(str(breadth_path))
        summary["missing_gold_market_breadth_daily_file"] = True
    if not distribution_path.exists():
        missing_paths.append(str(distribution_path))
        summary["missing_gold_stock_return_distribution_file"] = True
    if missing_paths:
        return None, summary, missing_paths

    breadth_row = _single_row_dict(
        connection,
        breadth_path,
        columns=("trade_date", *_BREADTH_VALUE_COLUMNS),
    )
    distribution_row = _single_row_dict(
        connection,
        distribution_path,
        columns=("trade_date", "flat_count", *_DISTRIBUTION_VALUE_COLUMNS, "total_count"),
    )
    summary["gold_market_breadth_daily_path"] = str(breadth_path)
    summary["gold_stock_return_distribution_path"] = str(distribution_path)
    summary["gold_market_breadth_row"] = breadth_row or {}
    summary["gold_stock_return_distribution_row"] = distribution_row or {}
    if breadth_row is None or distribution_row is None:
        return None, summary, missing_paths
    if breadth_row["trade_date"] != trade_date or distribution_row["trade_date"] != trade_date:
        return None, summary, missing_paths
    if int(breadth_row["total_count"]) != int(distribution_row["total_count"]):
        return None, summary, missing_paths
    if int(breadth_row["flat_count"]) != int(distribution_row["flat_count"]):
        return None, summary, missing_paths

    expected_row = {
        "trade_date": trade_date,
        "up_count": int(breadth_row["up_count"]),
        "down_count": int(breadth_row["down_count"]),
        "flat_count": int(breadth_row["flat_count"]),
        "total_count": int(breadth_row["total_count"]),
        "red_rate": float(breadth_row["red_rate"]),
    }
    for column in _DISTRIBUTION_VALUE_COLUMNS:
        expected_row[column] = int(distribution_row[column])
    return expected_row, summary, missing_paths


def _row_mismatches(
    *,
    actual_row: Mapping[str, Any],
    expected_row: Mapping[str, Any],
    columns: Sequence[str],
) -> list[dict[str, object]]:
    mismatches = []
    for column in columns:
        actual_value = actual_row.get(column)
        expected_value = expected_row.get(column)
        if column == "red_rate":
            matches = abs(float(actual_value) - float(expected_value)) < 0.000001
        else:
            matches = actual_value == expected_value
        if not matches:
            mismatches.append(
                {
                    "field": column,
                    "actual_value": actual_value,
                    "expected_value": expected_value,
                }
            )
    return mismatches


def batch_clickhouse_market_breadth_readiness(
    *,
    connection,
    lake_root_path: Path,
    clickhouse_client,
    expected_trade_dates: Sequence[str],
) -> ContinuityBatchReadiness:
    started_at = perf_counter()
    expected_trade_dates = tuple(str(value) for value in expected_trade_dates)
    rows_by_partition = fetch_clickhouse_market_breadth_rows_for_partitions(
        clickhouse_client,
        expected_trade_dates,
    )
    statuses: dict[str, ContinuityDateReadiness] = {}

    for trade_date in expected_trade_dates:
        rows = rows_by_partition.get(trade_date, [])
        summary: dict[str, object] = {
            "clickhouse_row_count": len(rows),
            "clickhouse_row_counts_by_partition": _clickhouse_summary_rows(
                rows_by_partition
            ),
        }
        if len(rows) == 0:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason="missing_clickhouse_row",
                missing_check_names=("ch_share_fact_market_breadth_row_count_is_one",),
                summary=summary,
            )
            continue
        if len(rows) != 1:
            statuses[trade_date] = _failed_status(
                trade_date=trade_date,
                reason="blocking_checks_failed",
                failed_check_names=("ch_share_fact_market_breadth_row_count_is_one",),
                summary=summary,
            )
            continue

        expected_row, expected_summary, missing_paths = _expected_clickhouse_row(
            connection=connection,
            lake_root_path=lake_root_path,
            trade_date=trade_date,
        )
        summary.update(expected_summary)
        if expected_row is None:
            statuses[trade_date] = _failed_status(
                trade_date=trade_date,
                reason="blocking_checks_failed",
                failed_check_names=(
                    "ch_share_fact_market_breadth_total_count_matches_gold",
                    "ch_share_fact_market_breadth_flat_count_matches_gold",
                    "ch_share_fact_market_breadth_breadth_fields_match_gold",
                    "ch_share_fact_market_breadth_distribution_fields_match_gold",
                ),
                missing_file_paths=missing_paths,
                summary=summary,
            )
            continue

        row = rows[0]
        failed: list[str] = []
        if row.get("trade_date") != trade_date:
            failed.append("ch_share_fact_market_breadth_date_matches_partition")
        if row.get("total_count") != expected_row["total_count"]:
            failed.append("ch_share_fact_market_breadth_total_count_matches_gold")
        if row.get("flat_count") != expected_row["flat_count"]:
            failed.append("ch_share_fact_market_breadth_flat_count_matches_gold")
        breadth_mismatches = _row_mismatches(
            actual_row=row,
            expected_row=expected_row,
            columns=_BREADTH_VALUE_COLUMNS,
        )
        distribution_mismatches = _row_mismatches(
            actual_row=row,
            expected_row=expected_row,
            columns=_DISTRIBUTION_VALUE_COLUMNS,
        )
        if breadth_mismatches:
            failed.append("ch_share_fact_market_breadth_breadth_fields_match_gold")
            summary["breadth_mismatch_samples"] = breadth_mismatches[:10]
        if distribution_mismatches:
            failed.append("ch_share_fact_market_breadth_distribution_fields_match_gold")
            summary["distribution_mismatch_samples"] = distribution_mismatches[:10]

        if failed:
            statuses[trade_date] = _failed_status(
                trade_date=trade_date,
                reason="blocking_checks_failed",
                failed_check_names=failed,
                summary=summary,
            )
        else:
            statuses[trade_date] = _ready_status(
                trade_date=trade_date,
                summary=summary,
            )

    return ContinuityBatchReadiness(
        expected_trade_dates=expected_trade_dates,
        statuses_by_trade_date=statuses,
        elapsed_ms=_elapsed_ms(started_at),
        scanned_file_count=sum(1 for rows in rows_by_partition.values() if rows),
    )


def batch_prod_clickhouse_market_breadth_readiness(
    *,
    local_clickhouse_client,
    prod_clickhouse_client,
    expected_trade_dates: Sequence[str],
) -> ContinuityBatchReadiness:
    started_at = perf_counter()
    expected_trade_dates = tuple(str(value) for value in expected_trade_dates)
    local_rows_by_partition = fetch_clickhouse_market_breadth_rows_for_partitions(
        local_clickhouse_client,
        expected_trade_dates,
    )
    prod_rows_by_partition = fetch_clickhouse_market_breadth_rows_for_partitions(
        prod_clickhouse_client,
        expected_trade_dates,
    )
    statuses: dict[str, ContinuityDateReadiness] = {}

    for trade_date in expected_trade_dates:
        prod_rows = prod_rows_by_partition.get(trade_date, [])
        local_rows = local_rows_by_partition.get(trade_date, [])
        summary: dict[str, object] = {
            "prod_clickhouse_row_count": len(prod_rows),
            "local_clickhouse_row_count": len(local_rows),
        }
        if len(prod_rows) == 0:
            statuses[trade_date] = ContinuityDateReadiness(
                trade_date=trade_date,
                ready=False,
                materialized=False,
                checks_passed=False,
                reason="missing_prod_clickhouse_row",
                missing_check_names=(
                    "prod_ch_share_fact_market_breadth_row_count_is_one",
                ),
                summary=summary,
            )
            continue
        if len(prod_rows) != 1 or len(local_rows) != 1:
            statuses[trade_date] = _failed_status(
                trade_date=trade_date,
                reason="blocking_checks_failed",
                failed_check_names=(
                    "prod_ch_share_fact_market_breadth_row_count_is_one",
                    "prod_ch_share_fact_market_breadth_row_matches_local",
                ),
                summary=summary,
            )
            continue

        prod_row = prod_rows[0]
        local_row = local_rows[0]
        failed: list[str] = []
        if prod_row.get("trade_date") != trade_date:
            failed.append("prod_ch_share_fact_market_breadth_date_matches_partition")
        mismatched_fields = [
            field
            for field, local_value in local_row.items()
            if prod_row.get(field) != local_value
        ]
        if mismatched_fields:
            failed.append("prod_ch_share_fact_market_breadth_row_matches_local")
            summary["mismatched_fields"] = mismatched_fields[:10]
        if str(prod_row.get("updated_at")) < str(local_row.get("updated_at")):
            failed.append("prod_ch_share_fact_market_breadth_updated_at_not_older_than_local")
            summary["local_updated_at"] = local_row.get("updated_at")
            summary["prod_updated_at"] = prod_row.get("updated_at")

        if failed:
            statuses[trade_date] = _failed_status(
                trade_date=trade_date,
                reason="blocking_checks_failed",
                failed_check_names=failed,
                summary=summary,
            )
        else:
            statuses[trade_date] = _ready_status(
                trade_date=trade_date,
                summary=summary,
            )

    return ContinuityBatchReadiness(
        expected_trade_dates=expected_trade_dates,
        statuses_by_trade_date=statuses,
        elapsed_ms=_elapsed_ms(started_at),
        scanned_file_count=sum(1 for rows in prod_rows_by_partition.values() if rows),
    )
