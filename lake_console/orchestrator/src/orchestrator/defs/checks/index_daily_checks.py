from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.assets.index_daily import (
    INDEX_DAILY_RAW_COLUMN_TYPES,
    INDEX_DAILY_SILVER_COLUMN_TYPES,
    raw_index_daily,
    silver_index_daily,
)
from orchestrator.defs.duckdb_sql import (
    INDEX_DAILY_RAW_COLUMNS,
    INDEX_DAILY_SILVER_COLUMNS,
    count_parquet_query,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.partitions import cn_a_index_ts_codes
from orchestrator.defs.paths import (
    raw_index_daily_path,
    silver_index_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


def _selected_partition_keys(context: dg.AssetCheckExecutionContext) -> tuple[str, ...]:
    return tuple(sorted(set(context.partition_keys)))


def _column_names(
    connection, path: Path, *, hive_partitioning: bool = False
) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=hive_partitioning)
    ).fetchall()
    return [row[0] for row in rows]


def _column_types(
    connection, path: Path, *, hive_partitioning: bool = False
) -> dict[str, str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=hive_partitioning)
    ).fetchall()
    return {row[0]: str(row[1]).upper() for row in rows}


def _row_count(connection, path: Path, *, hive_partitioning: bool = False) -> int:
    return int(
        connection.execute(
            count_parquet_query(path, hive_partitioning=hive_partitioning)
        ).fetchone()[0]
    )


def _sample_dicts(
    columns: Sequence[str], rows: Sequence[Sequence[Any]]
) -> list[dict[str, Any]]:
    samples = []
    for row in rows:
        sample = {}
        for column, value in zip(columns, row, strict=True):
            sample[column] = value.isoformat() if hasattr(value, "isoformat") else value
        samples.append(sample)
    return samples


def _blocking_value_result(passed: bool, metadata: dict[str, Any]) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=passed,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            extra_metadata=metadata,
        ),
    )


def _partition_count_summary(
    *,
    partition_keys: tuple[str, ...],
    missing_paths: Sequence[str],
    failed_partitions: Sequence[str],
) -> dict[str, int]:
    return {
        "partition_count": len(partition_keys),
        "missing_file_count": len(missing_paths),
        "failed_partition_count": len(failed_partitions),
    }


def _sum_result_count(results: dict[str, Any], key: str) -> int:
    return sum(int(result.get(key, 0) or 0) for result in results.values())


def _index_daily_next_action(
    *,
    missing_paths: Sequence[str],
    failed_partitions: Sequence[str],
    failure_hint: str,
) -> str:
    if not missing_paths and not failed_partitions:
        return "无需处理；等待下游按 readiness 消费指数日线分区。"
    if missing_paths:
        return "先生成缺失的 index_daily by-date 文件，再重新运行对应 asset/check。"
    return failure_hint


def _raw_file_contract_rule_summary(
    *,
    missing_paths: Sequence[str],
    results: dict[str, Any],
) -> list[dict[str, object]]:
    return [
        {"rule_name": "raw_index_daily_file_exists", "passed": not missing_paths},
        {
            "rule_name": "raw_index_daily_row_count_positive",
            "passed": _sum_result_count(results, "row_count") > 0
            and all(int(result["row_count"]) > 0 for result in results.values()),
        },
        {
            "rule_name": "raw_index_daily_required_columns_and_types",
            "passed": not any(
                result["missing_columns"]
                or result["unexpected_columns"]
                or result["type_mismatches"]
                for result in results.values()
            ),
        },
        {
            "rule_name": "raw_index_daily_key_not_null",
            "passed": _sum_result_count(results, "null_key_count") == 0,
        },
        {
            "rule_name": "raw_index_daily_partition_date_matches",
            "passed": _sum_result_count(results, "date_mismatch_count") == 0,
        },
        {
            "rule_name": "raw_index_daily_unique_ts_code_trade_date",
            "passed": _sum_result_count(results, "duplicate_key_count") == 0,
        },
    ]


def _coverage_summary_counts(coverage_results: dict[str, Any]) -> dict[str, int]:
    return {
        "missing_code_count": _sum_result_count(
            coverage_results,
            "missing_code_count",
        ),
        "extra_code_count": _sum_result_count(
            coverage_results,
            "extra_code_count",
        ),
        "missing_raw_present_count": _sum_result_count(
            coverage_results,
            "missing_raw_present_count",
        ),
    }


def _combined_next_action(failed_rule_names: Sequence[str]) -> str:
    if not failed_rule_names:
        return "无需处理；等待下游按 readiness 消费指数日线 silver 分区。"
    if any("row_count" in rule for rule in failed_rule_names):
        return "先确认 silver_index_daily 目标文件已生成且非空，再重新运行 checks。"
    if any("required_columns" in rule for rule in failed_rule_names):
        return "先核对 silver_index_daily Parquet schema 与字段类型，再重新生成分区。"
    if any("partition_date" in rule for rule in failed_rule_names):
        return "先核对文件内 trade_date 是否与分区日期一致，再重新生成该分区。"
    if any("unique" in rule or "duplicate" in rule for rule in failed_rule_names):
        return "先处理 ts_code + trade_date 重复键，再重新生成该分区。"
    return "先查看 failed_rule_names 对应子规则 metadata，修复后重新运行 checks。"


def _combined_check_result(
    *,
    partition_keys: tuple[str, ...],
    rule_results: Sequence[tuple[str, dg.AssetCheckResult]],
    check_scope: CheckScope,
) -> dg.AssetCheckResult:
    rule_summary = [
        {"rule_name": rule_name, "passed": bool(result.passed)}
        for rule_name, result in rule_results
    ]
    failed_rule_names = [
        rule_name for rule_name, result in rule_results if not bool(result.passed)
    ]
    summary = (
        f"通过：{len(partition_keys)} 个指数日线 silver 分区的 {len(rule_results)} 条聚合规则全部通过。"
        if not failed_rule_names
        else f"失败：{len(failed_rule_names)} / {len(rule_results)} 条指数日线 silver 聚合规则未通过。"
    )
    return dg.AssetCheckResult(
        passed=not failed_rule_names,
        metadata=build_check_metadata(
            check_scope=check_scope,
            extra_metadata={
                "summary": summary,
                "next_action": _combined_next_action(failed_rule_names),
                "rule_summary": rule_summary,
                "partition_keys": list(partition_keys),
                "rule_passed": {
                    rule_name: bool(result.passed)
                    for rule_name, result in rule_results
                },
                "failed_rule_names": failed_rule_names,
            },
        ),
    )


def _values_table_sql(values: Sequence[str], column_name: str) -> str:
    if not values:
        return f"(SELECT CAST(NULL AS VARCHAR) AS {column_name} WHERE FALSE)"
    rows = ", ".join(f"({duckdb_string(value)})" for value in values)
    return f"(VALUES {rows}) AS registered({column_name})"


def _required_columns_result(
    *,
    connection,
    path: Path,
    required_columns: tuple[str, ...],
    expected_types: dict[str, str],
) -> dict[str, Any]:
    columns = _column_names(connection, path)
    column_types = _column_types(connection, path)
    missing_columns = [column for column in required_columns if column not in columns]
    unexpected_columns = [
        column for column in columns if column not in required_columns
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
        "column_types": column_types,
        "required_columns": list(required_columns),
        "missing_columns": missing_columns,
        "unexpected_columns": unexpected_columns,
        "type_mismatches": type_mismatches,
    }


def evaluate_raw_index_daily_file_contract(
    partition_keys: tuple[str, ...],
    lake_root_path: Path,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    del duckdb
    results: dict[str, Any] = {}
    missing_paths = []
    with connect_configured_duckdb() as connection:
        for partition_key in partition_keys:
            path = raw_index_daily_path(lake_root_path, partition_key)
            if not path.exists():
                missing_paths.append(str(path))
                continue
            schema_result = _required_columns_result(
                connection=connection,
                path=path,
                required_columns=INDEX_DAILY_RAW_COLUMNS,
                expected_types=INDEX_DAILY_RAW_COLUMN_TYPES,
            )
            row_count = _row_count(connection, path)
            expected_trade_date = partition_key.replace("-", "")
            null_key_count = int(
                connection.execute(
                    f"""
                    SELECT count(*)
                    FROM {read_parquet(path, hive_partitioning=False)}
                    WHERE ts_code IS NULL
                       OR trim(CAST(ts_code AS VARCHAR)) = ''
                       OR trade_date IS NULL
                       OR trim(CAST(trade_date AS VARCHAR)) = ''
                    """
                ).fetchone()[0]
            )
            date_mismatch_count = int(
                connection.execute(
                    f"""
                    SELECT count(*)
                    FROM {read_parquet(path, hive_partitioning=False)}
                    WHERE CAST(trade_date AS VARCHAR) != {duckdb_string(expected_trade_date)}
                    """
                ).fetchone()[0]
            )
            duplicate_key_count = int(
                connection.execute(
                    f"""
                    SELECT count(*)
                    FROM (
                      SELECT ts_code, trade_date
                      FROM {read_parquet(path, hive_partitioning=False)}
                      GROUP BY ts_code, trade_date
                      HAVING count(*) > 1
                    ) duplicate_keys
                    """
                ).fetchone()[0]
            )
            duplicate_rows = connection.execute(
                f"""
                SELECT ts_code, trade_date, count(*) AS row_count
                FROM {read_parquet(path, hive_partitioning=False)}
                GROUP BY ts_code, trade_date
                HAVING count(*) > 1
                ORDER BY ts_code, trade_date
                LIMIT 10
                """
            ).fetchall()
            results[partition_key] = {
                **schema_result,
                "row_count": row_count,
                "null_key_count": null_key_count,
                "date_mismatch_count": date_mismatch_count,
                "duplicate_key_count": duplicate_key_count,
                "duplicate_samples": _sample_dicts(
                    ["ts_code", "trade_date", "row_count"],
                    duplicate_rows,
                ),
            }

    failed_partitions = [
        partition_key
        for partition_key, result in results.items()
        if result["row_count"] <= 0
        or result["missing_columns"]
        or result["unexpected_columns"]
        or result["type_mismatches"]
        or result["null_key_count"]
        or result["date_mismatch_count"]
        or result["duplicate_key_count"]
    ]
    passed = not missing_paths and not failed_partitions
    contract_summary = {
        **_partition_count_summary(
            partition_keys=partition_keys,
            missing_paths=missing_paths,
            failed_partitions=failed_partitions,
        ),
        "row_count": _sum_result_count(results, "row_count"),
        "null_key_count": _sum_result_count(results, "null_key_count"),
        "date_mismatch_count": _sum_result_count(results, "date_mismatch_count"),
        "duplicate_key_count": _sum_result_count(results, "duplicate_key_count"),
    }
    return dg.AssetCheckResult(
        passed=passed,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            extra_metadata={
                "summary": (
                    f"通过：{len(partition_keys)} 个 raw_index_daily by-date 文件契约全部通过。"
                    if passed
                    else f"失败：raw_index_daily 有 {len(missing_paths)} 个缺失文件、{len(failed_partitions)} 个失败分区。"
                ),
                "next_action": _index_daily_next_action(
                    missing_paths=missing_paths,
                    failed_partitions=failed_partitions,
                    failure_hint=(
                        "先查看 contract_summary 和 failed_partitions，修复 schema、日期、空 key 或重复键后重跑。"
                    ),
                ),
                "rule_summary": _raw_file_contract_rule_summary(
                    missing_paths=missing_paths,
                    results=results,
                ),
                "contract_summary": contract_summary,
                "partition_keys": list(partition_keys),
                "results": results,
                "missing_file_paths": missing_paths,
                "failed_partitions": failed_partitions,
            },
        ),
    )


def evaluate_raw_index_daily_code_coverage(
    partition_keys: tuple[str, ...],
    lake_root_path: Path,
    duckdb: DuckDBResource,
    registered_index_codes: Sequence[str],
) -> dg.AssetCheckResult:
    del duckdb
    expected_codes = tuple(sorted(set(str(code).strip() for code in registered_index_codes)))
    if not expected_codes or any(not code for code in expected_codes):
        raise RuntimeError(f"{cn_a_index_ts_codes.name} has no registered partition keys.")
    expected_codes_sql = _values_table_sql(expected_codes, "ts_code")
    coverage_results: dict[str, Any] = {}
    missing_paths = []
    with connect_configured_duckdb() as connection:
        for partition_key in partition_keys:
            path = raw_index_daily_path(lake_root_path, partition_key)
            if not path.exists():
                missing_paths.append(str(path))
                continue
            observed_codes_sql = f"""
            SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
            FROM {read_parquet(path, hive_partitioning=False)}
            """
            coverage_row = connection.execute(
                f"""
                WITH expected AS (
                  SELECT ts_code FROM {expected_codes_sql}
                ),
                observed AS (
                  {observed_codes_sql}
                )
                SELECT
                  (SELECT count(*) FROM expected) AS expected_code_count,
                  (SELECT count(*) FROM observed) AS observed_code_count,
                  (
                    SELECT count(*)
                    FROM expected
                    LEFT JOIN observed USING (ts_code)
                    WHERE observed.ts_code IS NULL
                  ) AS missing_code_count,
                  (
                    SELECT count(*)
                    FROM observed
                    LEFT JOIN expected USING (ts_code)
                    WHERE expected.ts_code IS NULL
                  ) AS extra_code_count
                """
            ).fetchone()
            missing_rows = connection.execute(
                f"""
                WITH expected AS (
                  SELECT ts_code FROM {expected_codes_sql}
                ),
                observed AS (
                  {observed_codes_sql}
                )
                SELECT expected.ts_code
                FROM expected
                LEFT JOIN observed USING (ts_code)
                WHERE observed.ts_code IS NULL
                ORDER BY expected.ts_code
                LIMIT 10
                """
            ).fetchall()
            extra_rows = connection.execute(
                f"""
                WITH expected AS (
                  SELECT ts_code FROM {expected_codes_sql}
                ),
                observed AS (
                  {observed_codes_sql}
                )
                SELECT observed.ts_code
                FROM observed
                LEFT JOIN expected USING (ts_code)
                WHERE expected.ts_code IS NULL
                ORDER BY observed.ts_code
                LIMIT 10
                """
            ).fetchall()
            expected_count = int(coverage_row[0])
            observed_count = int(coverage_row[1])
            missing_count = int(coverage_row[2])
            extra_count = int(coverage_row[3])
            coverage_results[partition_key] = {
                "expected_code_count": expected_count,
                "observed_code_count": observed_count,
                "missing_code_count": missing_count,
                "extra_code_count": extra_count,
                "coverage_rate": (
                    round((expected_count - missing_count) * 100.0 / expected_count, 4)
                    if expected_count
                    else 0.0
                ),
                "missing_code_samples": [row[0] for row in missing_rows],
                "extra_code_samples": [row[0] for row in extra_rows],
            }

    failed_partitions = [
        partition_key
        for partition_key, result in coverage_results.items()
        if result["missing_code_count"] or result["extra_code_count"]
    ]
    passed = not missing_paths and not failed_partitions
    coverage_summary = {
        **_partition_count_summary(
            partition_keys=partition_keys,
            missing_paths=missing_paths,
            failed_partitions=failed_partitions,
        ),
        **_coverage_summary_counts(coverage_results),
        "expected_code_count": len(expected_codes),
    }
    return _blocking_value_result(
        passed,
        {
            "summary": (
                f"通过：raw_index_daily 覆盖 DG 管理的 {len(expected_codes)} 个指数代码。"
                if passed
                else "失败：raw_index_daily code 覆盖与 DG 动态分区不一致。"
            ),
            "next_action": _index_daily_next_action(
                missing_paths=missing_paths,
                failed_partitions=failed_partitions,
                failure_hint=(
                    "先核对 DG 动态分区、prod core serving 和 raw_index_daily 文件中的缺失/多余指数代码，再重跑。"
                ),
            ),
            "rule_summary": [
                {
                    "rule_name": "raw_index_daily_file_exists",
                    "passed": not missing_paths,
                },
                {
                    "rule_name": "raw_index_daily_code_set_matches_dg_partitions",
                    "passed": not failed_partitions,
                },
            ],
            "coverage_summary": coverage_summary,
            "partition_keys": list(partition_keys),
            "expected_code_count": len(expected_codes),
            "coverage_results": coverage_results,
            "missing_file_paths": missing_paths,
            "failed_partitions": failed_partitions,
        },
    )


def evaluate_silver_index_daily_row_count_positive(
    partition_keys: tuple[str, ...],
    lake_root_path: Path,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    row_counts: dict[str, int] = {}
    missing_paths = []
    with connect_configured_duckdb() as connection:
        for partition_key in partition_keys:
            path = silver_index_daily_path(lake_root_path, partition_key)
            if not path.exists():
                missing_paths.append(str(path))
                continue
            row_counts[partition_key] = _row_count(connection, path)

    zero_row_partitions = [
        partition_key
        for partition_key, row_count in row_counts.items()
        if row_count <= 0
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not zero_row_partitions,
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            extra_metadata={
                "partition_keys": list(partition_keys),
                "row_counts": row_counts,
                "missing_file_paths": missing_paths,
                "zero_row_partitions": zero_row_partitions,
            },
        ),
    )


def evaluate_silver_index_daily_required_columns_and_types(
    partition_keys: tuple[str, ...],
    lake_root_path: Path,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    results: dict[str, Any] = {}
    missing_paths = []
    with connect_configured_duckdb() as connection:
        for partition_key in partition_keys:
            path = silver_index_daily_path(lake_root_path, partition_key)
            if not path.exists():
                missing_paths.append(str(path))
                continue
            results[partition_key] = _required_columns_result(
                connection=connection,
                path=path,
                required_columns=INDEX_DAILY_SILVER_COLUMNS,
                expected_types=INDEX_DAILY_SILVER_COLUMN_TYPES,
            )

    failed_partitions = [
        partition_key
        for partition_key, result in results.items()
        if result["missing_columns"]
        or result["unexpected_columns"]
        or result["type_mismatches"]
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            extra_metadata={
                "partition_keys": list(partition_keys),
                "results": results,
                "missing_file_paths": missing_paths,
                "failed_partitions": failed_partitions,
            },
        ),
    )


def evaluate_silver_index_daily_partition_date_matches(
    partition_keys: tuple[str, ...],
    lake_root_path: Path,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    mismatch_counts: dict[str, int] = {}
    mismatch_samples: dict[str, list[dict[str, Any]]] = {}
    missing_paths = []
    with connect_configured_duckdb() as connection:
        for partition_key in partition_keys:
            path = silver_index_daily_path(lake_root_path, partition_key)
            if not path.exists():
                missing_paths.append(str(path))
                continue
            mismatch_rows_sql = f"""
            SELECT ts_code, trade_date
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE trade_date IS NULL
               OR CAST(trade_date AS DATE) != DATE {duckdb_string(partition_key)}
            """
            mismatch_counts[partition_key] = int(
                connection.execute(
                    f"SELECT count(*) FROM ({mismatch_rows_sql}) mismatch_rows"
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                {mismatch_rows_sql}
                ORDER BY ts_code, trade_date
                LIMIT 10
                """
            ).fetchall()
            mismatch_samples[partition_key] = _sample_dicts(
                ["ts_code", "trade_date"], rows
            )

    failed_partitions = [
        partition_key
        for partition_key, mismatch_count in mismatch_counts.items()
        if mismatch_count
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "partition_keys": list(partition_keys),
                "mismatch_counts": mismatch_counts,
                "mismatch_samples": mismatch_samples,
                "missing_file_paths": missing_paths,
                "failed_partitions": failed_partitions,
            },
        ),
    )


def evaluate_silver_index_daily_unique_ts_code_trade_date(
    partition_keys: tuple[str, ...],
    lake_root_path: Path,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    duplicate_counts: dict[str, int] = {}
    duplicate_samples: dict[str, list[dict[str, Any]]] = {}
    missing_paths = []
    with connect_configured_duckdb() as connection:
        for partition_key in partition_keys:
            path = silver_index_daily_path(lake_root_path, partition_key)
            if not path.exists():
                missing_paths.append(str(path))
                continue
            duplicate_keys_sql = f"""
            SELECT ts_code, trade_date, count(*) AS row_count
            FROM {read_parquet(path, hive_partitioning=False)}
            GROUP BY ts_code, trade_date
            HAVING count(*) > 1
            """
            duplicate_counts[partition_key] = int(
                connection.execute(
                    f"SELECT count(*) FROM ({duplicate_keys_sql}) duplicate_keys"
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                {duplicate_keys_sql}
                ORDER BY ts_code, trade_date
                LIMIT 10
                """
            ).fetchall()
            duplicate_samples[partition_key] = _sample_dicts(
                ["ts_code", "trade_date", "row_count"], rows
            )

    failed_partitions = [
        partition_key
        for partition_key, duplicate_count in duplicate_counts.items()
        if duplicate_count
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata=build_check_metadata(
            check_scope=CheckScope.KEY_UNIQUENESS,
            extra_metadata={
                "partition_keys": list(partition_keys),
                "duplicate_counts": duplicate_counts,
                "duplicate_samples": duplicate_samples,
                "missing_file_paths": missing_paths,
                "failed_partitions": failed_partitions,
            },
        ),
    )


def evaluate_silver_index_daily_conflicting_duplicate_absent(
    partition_keys: tuple[str, ...],
    lake_root_path: Path,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    conflict_counts: dict[str, int] = {}
    conflict_samples: dict[str, list[dict[str, Any]]] = {}
    missing_paths = []
    with connect_configured_duckdb() as connection:
        for partition_key in partition_keys:
            path = silver_index_daily_path(lake_root_path, partition_key)
            if not path.exists():
                missing_paths.append(str(path))
                continue
            conflict_counts[partition_key] = int(
                connection.execute(
                    f"""
                    SELECT count(*) AS conflict_key_count
                    FROM (
                      SELECT ts_code, trade_date
                      FROM {read_parquet(path, hive_partitioning=False)}
                      GROUP BY ts_code, trade_date
                      HAVING count(*) > 1
                    ) conflict_keys
                    """
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT ts_code, trade_date, count(*) AS version_count
                FROM {read_parquet(path, hive_partitioning=False)}
                GROUP BY ts_code, trade_date
                HAVING count(*) > 1
                ORDER BY ts_code, trade_date
                LIMIT 10
                """
            ).fetchall()
            conflict_samples[partition_key] = _sample_dicts(
                ["ts_code", "trade_date", "version_count"],
                rows,
            )

    failed_partitions = [
        partition_key
        for partition_key, conflict_count in conflict_counts.items()
        if conflict_count
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata=build_check_metadata(
            check_scope=CheckScope.KEY_UNIQUENESS,
            extra_metadata={
                "partition_keys": list(partition_keys),
                "conflict_counts": conflict_counts,
                "conflict_samples": conflict_samples,
                "missing_file_paths": missing_paths,
                "failed_partitions": failed_partitions,
            },
        ),
    )


def evaluate_silver_index_daily_price_sanity(
    partition_keys: tuple[str, ...],
    lake_root_path: Path,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    invalid_counts: dict[str, int] = {}
    invalid_samples: dict[str, list[dict[str, Any]]] = {}
    missing_paths = []
    with connect_configured_duckdb() as connection:
        for partition_key in partition_keys:
            path = silver_index_daily_path(lake_root_path, partition_key)
            if not path.exists():
                missing_paths.append(str(path))
                continue
            invalid_rows_sql = f"""
            SELECT ts_code, trade_date, open, high, low, close, pre_close
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE open < 0
               OR high < 0
               OR low < 0
               OR close < 0
               OR pre_close < 0
               OR high < low
               OR open > high
               OR open < low
               OR close > high
               OR close < low
            """
            invalid_counts[partition_key] = int(
                connection.execute(
                    f"SELECT count(*) FROM ({invalid_rows_sql}) invalid_rows"
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                {invalid_rows_sql}
                ORDER BY ts_code, trade_date
                LIMIT 10
                """
            ).fetchall()
            invalid_samples[partition_key] = _sample_dicts(
                ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close"],
                rows,
            )

    failed_partitions = [
        partition_key
        for partition_key, invalid_count in invalid_counts.items()
        if invalid_count
    ]
    return dg.AssetCheckResult(
        passed=not missing_paths and not failed_partitions,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "partition_keys": list(partition_keys),
                "invalid_counts": invalid_counts,
                "invalid_samples": invalid_samples,
                "missing_file_paths": missing_paths,
                "failed_partitions": failed_partitions,
            },
        ),
    )


def evaluate_silver_index_daily_registered_code_coverage(
    partition_keys: tuple[str, ...],
    lake_root_path: Path,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    del duckdb
    coverage_results: dict[str, Any] = {}
    missing_paths = []
    with connect_configured_duckdb() as connection:
        for partition_key in partition_keys:
            silver_path = silver_index_daily_path(lake_root_path, partition_key)
            raw_path = raw_index_daily_path(lake_root_path, partition_key)
            if not raw_path.exists():
                missing_paths.append(str(raw_path))
            if not silver_path.exists():
                missing_paths.append(str(silver_path))
                continue
            if not raw_path.exists():
                continue
            raw_present_codes_sql = f"""
            SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code
            FROM {read_parquet(raw_path, hive_partitioning=False)}
            WHERE CAST(trade_date AS VARCHAR) = {duckdb_string(partition_key.replace("-", ""))}
            """
            missing_codes_sql = f"""
            SELECT raw_present.ts_code
            FROM ({raw_present_codes_sql}) raw_present
            LEFT JOIN {read_parquet(silver_path, hive_partitioning=False)} daily
              ON raw_present.ts_code = daily.ts_code
            WHERE daily.ts_code IS NULL
            """
            extra_codes_sql = f"""
            SELECT daily.ts_code
            FROM {read_parquet(silver_path, hive_partitioning=False)} daily
            LEFT JOIN ({raw_present_codes_sql}) raw_present
              ON daily.ts_code = raw_present.ts_code
            WHERE raw_present.ts_code IS NULL
            """
            raw_present_count = int(
                connection.execute(
                    f"SELECT count(*) FROM ({raw_present_codes_sql}) raw_present_codes"
                ).fetchone()[0]
            )
            missing_count = int(
                connection.execute(
                    f"SELECT count(*) FROM ({missing_codes_sql}) missing_codes"
                ).fetchone()[0]
            )
            extra_count = int(
                connection.execute(
                    f"SELECT count(*) FROM ({extra_codes_sql}) extra_codes"
                ).fetchone()[0]
            )
            silver_row_count = _row_count(connection, silver_path)
            missing_rows = connection.execute(
                f"""
                {missing_codes_sql}
                ORDER BY ts_code
                LIMIT 20
                """
            ).fetchall()
            extra_rows = connection.execute(
                f"""
                {extra_codes_sql}
                ORDER BY ts_code
                LIMIT 20
                """
            ).fetchall()
            coverage_results[partition_key] = {
                "raw_file_path": str(raw_path),
                "raw_present_code_count": raw_present_count,
                "silver_row_count": silver_row_count,
                "missing_raw_present_count": missing_count,
                "extra_count": extra_count,
                "coverage_rate": (
                    round(
                        (raw_present_count - missing_count)
                        * 100.0
                        / raw_present_count,
                        4,
                    )
                    if raw_present_count
                    else 0.0
                ),
                "missing_raw_present_samples": [row[0] for row in missing_rows],
                "extra_samples": [row[0] for row in extra_rows],
            }

    passed = not missing_paths and all(
        result["missing_raw_present_count"] == 0 and result["extra_count"] == 0
        for result in coverage_results.values()
    )
    failed_partitions = [
        partition_key
        for partition_key, result in coverage_results.items()
        if result["missing_raw_present_count"] or result["extra_count"]
    ]
    coverage_summary = {
        **_partition_count_summary(
            partition_keys=partition_keys,
            missing_paths=missing_paths,
            failed_partitions=failed_partitions,
        ),
        **_coverage_summary_counts(coverage_results),
        "extra_code_count": _sum_result_count(coverage_results, "extra_count"),
    }
    return _blocking_value_result(
        passed,
        {
            "summary": (
                "通过：silver_index_daily code set 与同日 raw_index_daily 完全一致。"
                if passed
                else "失败：silver_index_daily 与同日 raw_index_daily 的 code set 不一致。"
            ),
            "next_action": _index_daily_next_action(
                missing_paths=missing_paths,
                failed_partitions=failed_partitions,
                failure_hint="先按 coverage_summary 修复 silver 缺失或多余代码，再重跑。",
            ),
            "rule_summary": [
                {
                    "rule_name": "index_daily_raw_and_silver_files_exist",
                    "passed": not missing_paths,
                },
                {
                    "rule_name": "silver_index_daily_code_set_matches_raw",
                    "passed": not failed_partitions,
                },
            ],
            "coverage_summary": coverage_summary,
            "partition_keys": list(partition_keys),
            "coverage_results": coverage_results,
            "missing_file_paths": missing_paths,
        },
    )


@dg.asset_check(asset=raw_index_daily, blocking=True)
def raw_index_daily_file_contract_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return evaluate_raw_index_daily_file_contract(
        _selected_partition_keys(context),
        lake_root.root(),
        duckdb,
    )


@dg.asset_check(asset=raw_index_daily, blocking=True)
def raw_index_daily_code_coverage_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    registered_index_codes = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_index_ts_codes.name))
    )
    return evaluate_raw_index_daily_code_coverage(
        _selected_partition_keys(context),
        lake_root.root(),
        duckdb,
        registered_index_codes,
    )


@dg.asset_check(asset=silver_index_daily, blocking=True)
def silver_index_daily_contract_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_keys = _selected_partition_keys(context)
    lake_root_path = lake_root.root()
    return _combined_check_result(
        partition_keys=partition_keys,
        check_scope=CheckScope.SCHEMA,
        rule_results=(
            (
                "silver_index_daily_row_count_positive",
                evaluate_silver_index_daily_row_count_positive(
                    partition_keys,
                    lake_root_path,
                    duckdb,
                ),
            ),
            (
                "silver_index_daily_required_columns_and_types",
                evaluate_silver_index_daily_required_columns_and_types(
                    partition_keys,
                    lake_root_path,
                    duckdb,
                ),
            ),
            (
                "silver_index_daily_partition_date_matches",
                evaluate_silver_index_daily_partition_date_matches(
                    partition_keys,
                    lake_root_path,
                    duckdb,
                ),
            ),
        ),
    )


@dg.asset_check(asset=silver_index_daily, blocking=True)
def silver_index_daily_key_integrity_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    partition_keys = _selected_partition_keys(context)
    lake_root_path = lake_root.root()
    return _combined_check_result(
        partition_keys=partition_keys,
        check_scope=CheckScope.KEY_UNIQUENESS,
        rule_results=(
            (
                "silver_index_daily_unique_ts_code_trade_date",
                evaluate_silver_index_daily_unique_ts_code_trade_date(
                    partition_keys,
                    lake_root_path,
                    duckdb,
                ),
            ),
            (
                "silver_index_daily_conflicting_duplicate_absent",
                evaluate_silver_index_daily_conflicting_duplicate_absent(
                    partition_keys,
                    lake_root_path,
                    duckdb,
                ),
            ),
        ),
    )


@dg.asset_check(asset=silver_index_daily, blocking=True)
def silver_index_daily_value_domain_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return evaluate_silver_index_daily_price_sanity(
        _selected_partition_keys(context),
        lake_root.root(),
        duckdb,
    )


@dg.asset_check(
    asset=silver_index_daily,
    additional_deps=[raw_index_daily],
    blocking=True,
)
def silver_index_daily_registered_code_coverage_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return evaluate_silver_index_daily_registered_code_coverage(
        _selected_partition_keys(context),
        lake_root.root(),
        duckdb,
    )
