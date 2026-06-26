from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.assets.stock_basic import silver_stock_basic
from orchestrator.defs.assets.stock_identity_map import (
    STOCK_IDENTITY_ALLOWED_CONFIDENCE,
    STOCK_IDENTITY_ALLOWED_SOURCES,
    STOCK_IDENTITY_COLUMN_TYPES,
    silver_stock_identity_map,
)
from orchestrator.defs.duckdb_sql import (
    count_parquet_query,
    describe_parquet_query,
    read_parquet,
)
from orchestrator.defs.paths import (
    silver_stock_basic_path,
    silver_stock_identity_map_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from orchestrator.seeds.basic.stock_identity_mappings import (
    load_stock_identity_mapping_seed,
)


def _describe_schema(connection, path: Path) -> dict[str, str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=False)
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def _column_names(connection, path: Path) -> list[str]:
    return list(_describe_schema(connection, path).keys())


def _row_count(connection, path: Path) -> int:
    return int(
        connection.execute(
            count_parquet_query(path, hive_partitioning=False)
        ).fetchone()[0]
    )


def _sample_dicts(
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> list[dict[str, Any]]:
    samples = []
    for row in rows:
        sample = {}
        for column, value in zip(columns, row, strict=True):
            sample[column] = value.isoformat() if hasattr(value, "isoformat") else value
        samples.append(sample)
    return samples


def _missing_file_result(path: Path) -> dg.AssetCheckResult:
    return dg.AssetCheckResult(
        passed=False,
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            file_path=path,
            missing_file_paths=[path],
            extra_metadata={
                "summary": "股票身份映射输入或目标文件不存在，当前 check 无法继续验证。",
                "next_action": "先确认 silver_stock_basic、silver_namechange 和 stock_identity_map 目标文件已生成。",
                "rule_summary": ["file_exists"],
                "missing_file": True,
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
                    "股票身份映射聚合检查通过。"
                    if not failed_rule_names
                    else "股票身份映射聚合检查失败，请先看 failed_rule_names。"
                ),
                "next_action": (
                    "无需处理，身份映射可供下游归一历史代码。"
                    if not failed_rule_names
                    else "按 failed_rule_names 修复 schema、唯一键、seed 引用或枚举域后再重跑。"
                ),
                "rule_summary": [rule_name for rule_name, _ in rule_results],
                "rule_passed": {
                    rule_name: bool(result.passed)
                    for rule_name, result in rule_results
                },
                "failed_rule_names": failed_rule_names,
            },
        ),
    )


def silver_stock_identity_map_file_exists(
    lake_root: LakeRootResource,
) -> dg.AssetCheckResult:
    path = silver_stock_identity_map_path(lake_root.root())
    return dg.AssetCheckResult(
        passed=path.exists(),
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            file_path=path,
            extra_metadata={"exists": path.exists()},
        ),
    )


def silver_stock_identity_map_row_count_positive(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_stock_identity_map_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    with connect_configured_duckdb() as connection:
        checked_row_count = _row_count(connection, path)
    return dg.AssetCheckResult(
        passed=checked_row_count > 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.ROW_COUNT,
            checked_row_count=checked_row_count,
            file_path=path,
        ),
    )


def silver_stock_identity_map_schema_matches_contract(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_stock_identity_map_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    with connect_configured_duckdb() as connection:
        observed_schema = _describe_schema(connection, path)
        checked_row_count = _row_count(connection, path)
    expected_schema = STOCK_IDENTITY_COLUMN_TYPES
    missing_columns = [column for column in expected_schema if column not in observed_schema]
    extra_columns = [column for column in observed_schema if column not in expected_schema]
    type_mismatches = {
        column: {"expected": expected_type, "actual": observed_schema.get(column)}
        for column, expected_type in expected_schema.items()
        if observed_schema.get(column) != expected_type
    }
    return dg.AssetCheckResult(
        passed=not missing_columns and not extra_columns and not type_mismatches,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            checked_row_count=checked_row_count,
            file_path=path,
            extra_metadata={
                "observed_schema": observed_schema,
                "expected_schema": expected_schema,
                "missing_columns": missing_columns,
                "extra_columns": extra_columns,
                "type_mismatches": type_mismatches,
            },
        ),
    )


def silver_stock_identity_map_source_ts_code_present(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_stock_identity_map_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    with connect_configured_duckdb() as connection:
        failed_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM {read_parquet(path, hive_partitioning=False)}
                WHERE source_ts_code IS NULL OR trim(source_ts_code) = ''
                """
            ).fetchone()[0]
        )
        checked_row_count = _row_count(connection, path)
    return dg.AssetCheckResult(
        passed=failed_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            checked_row_count=checked_row_count,
            failed_row_count=failed_count,
            file_path=path,
        ),
    )


def silver_stock_identity_map_source_ts_code_unique(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_stock_identity_map_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    with connect_configured_duckdb() as connection:
        rows = connection.execute(
            f"""
            SELECT source_ts_code, count(*) AS duplicate_count
            FROM {read_parquet(path, hive_partitioning=False)}
            GROUP BY source_ts_code
            HAVING count(*) > 1
            ORDER BY duplicate_count DESC, source_ts_code
            LIMIT 10
            """
        ).fetchall()
        failed_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM (
                  SELECT source_ts_code
                  FROM {read_parquet(path, hive_partitioning=False)}
                  GROUP BY source_ts_code
                  HAVING count(*) > 1
                )
                """
            ).fetchone()[0]
        )
        checked_row_count = _row_count(connection, path)
    return dg.AssetCheckResult(
        passed=failed_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.KEY_UNIQUENESS,
            checked_row_count=checked_row_count,
            failed_row_count=failed_count,
            file_path=path,
            extra_metadata={
                "duplicate_samples": _sample_dicts(
                    ["source_ts_code", "duplicate_count"],
                    rows,
                )
            },
        ),
    )


def silver_stock_identity_map_latest_ts_code_present(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_stock_identity_map_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    with connect_configured_duckdb() as connection:
        failed_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM {read_parquet(path, hive_partitioning=False)}
                WHERE latest_ts_code IS NULL OR trim(latest_ts_code) = ''
                """
            ).fetchone()[0]
        )
        checked_row_count = _row_count(connection, path)
    return dg.AssetCheckResult(
        passed=failed_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            checked_row_count=checked_row_count,
            failed_row_count=failed_count,
            file_path=path,
        ),
    )


def silver_stock_identity_map_latest_code_exists_in_stock_basic(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    identity_path = silver_stock_identity_map_path(lake_root.root())
    stock_basic_path = silver_stock_basic_path(lake_root.root())
    for path in (identity_path, stock_basic_path):
        if not path.exists():
            return _missing_file_result(path)
    with connect_configured_duckdb() as connection:
        rows = connection.execute(
            f"""
            SELECT identity_map.latest_ts_code, count(*) AS row_count
            FROM {read_parquet(identity_path, hive_partitioning=False)} identity_map
            LEFT JOIN {read_parquet(stock_basic_path, hive_partitioning=False)} basic
              ON identity_map.latest_ts_code = basic.ts_code
            WHERE basic.ts_code IS NULL
            GROUP BY identity_map.latest_ts_code
            ORDER BY row_count DESC, latest_ts_code
            LIMIT 10
            """
        ).fetchall()
        failed_count = int(
            connection.execute(
                f"""
                SELECT count(DISTINCT identity_map.latest_ts_code)
                FROM {read_parquet(identity_path, hive_partitioning=False)} identity_map
                LEFT JOIN {read_parquet(stock_basic_path, hive_partitioning=False)} basic
                  ON identity_map.latest_ts_code = basic.ts_code
                WHERE basic.ts_code IS NULL
                """
            ).fetchone()[0]
        )
        checked_row_count = _row_count(connection, identity_path)
    return dg.AssetCheckResult(
        passed=failed_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.REFERENTIAL_INTEGRITY,
            checked_row_count=checked_row_count,
            failed_row_count=failed_count,
            file_path=identity_path,
            input_file_paths=[stock_basic_path],
            extra_metadata={
                "missing_latest_code_samples": _sample_dicts(
                    ["latest_ts_code", "row_count"],
                    rows,
                )
            },
        ),
    )


def silver_stock_identity_map_known_identity_source(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _enum_check(
        lake_root=lake_root,
        duckdb=duckdb,
        field_name="identity_source",
        allowed_values=tuple(sorted(STOCK_IDENTITY_ALLOWED_SOURCES)),
    )


def silver_stock_identity_map_known_confidence(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _enum_check(
        lake_root=lake_root,
        duckdb=duckdb,
        field_name="confidence",
        allowed_values=tuple(sorted(STOCK_IDENTITY_ALLOWED_CONFIDENCE)),
    )


def silver_stock_identity_map_date_ranges_valid(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_stock_identity_map_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    with connect_configured_duckdb() as connection:
        rows = connection.execute(
            f"""
            SELECT source_ts_code, latest_ts_code, valid_from, valid_to
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE valid_from IS NULL
               OR (valid_to IS NOT NULL AND valid_to < valid_from)
            LIMIT 10
            """
        ).fetchall()
        failed_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM {read_parquet(path, hive_partitioning=False)}
                WHERE valid_from IS NULL
                   OR (valid_to IS NOT NULL AND valid_to < valid_from)
                """
            ).fetchone()[0]
        )
        checked_row_count = _row_count(connection, path)
    return dg.AssetCheckResult(
        passed=failed_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            checked_row_count=checked_row_count,
            failed_row_count=failed_count,
            file_path=path,
            extra_metadata={
                "invalid_date_range_samples": _sample_dicts(
                    ["source_ts_code", "latest_ts_code", "valid_from", "valid_to"],
                    rows,
                )
            },
        ),
    )


def silver_stock_identity_map_conflicting_mapping_absent(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_stock_identity_map_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    with connect_configured_duckdb() as connection:
        rows = connection.execute(
            f"""
            SELECT source_ts_code, count(DISTINCT latest_ts_code) AS latest_code_count
            FROM {read_parquet(path, hive_partitioning=False)}
            GROUP BY source_ts_code
            HAVING count(DISTINCT latest_ts_code) > 1
            ORDER BY latest_code_count DESC, source_ts_code
            LIMIT 10
            """
        ).fetchall()
        failed_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM (
                  SELECT source_ts_code
                  FROM {read_parquet(path, hive_partitioning=False)}
                  GROUP BY source_ts_code
                  HAVING count(DISTINCT latest_ts_code) > 1
                )
                """
            ).fetchone()[0]
        )
        checked_row_count = _row_count(connection, path)
    return dg.AssetCheckResult(
        passed=failed_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.RECONCILIATION,
            checked_row_count=checked_row_count,
            failed_row_count=failed_count,
            file_path=path,
            extra_metadata={
                "conflict_samples": _sample_dicts(
                    ["source_ts_code", "latest_code_count"],
                    rows,
                )
            },
        ),
    )


def silver_stock_identity_map_seed_latest_code_explainable(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    stock_basic_path = silver_stock_basic_path(lake_root.root())
    if not stock_basic_path.exists():
        return _missing_file_result(stock_basic_path)
    try:
        seed_rows = load_stock_identity_mapping_seed()
    except (FileNotFoundError, ValueError) as error:
        return dg.AssetCheckResult(
            passed=False,
            metadata=build_check_metadata(
                check_scope=CheckScope.REFERENTIAL_INTEGRITY,
                file_path=stock_basic_path,
                extra_metadata={"seed_error": str(error)},
            ),
        )
    seed_latest_codes = tuple(sorted({row.latest_ts_code for row in seed_rows}))
    with connect_configured_duckdb() as connection:
        missing_codes = [
            code
            for code in seed_latest_codes
            if connection.execute(
                f"""
                SELECT count(*)
                FROM {read_parquet(stock_basic_path, hive_partitioning=False)}
                WHERE ts_code = ?
                """,
                [code],
            ).fetchone()[0]
            == 0
        ]
        checked_row_count = _row_count(connection, stock_basic_path)
    return dg.AssetCheckResult(
        passed=not missing_codes,
        metadata=build_check_metadata(
            check_scope=CheckScope.REFERENTIAL_INTEGRITY,
            checked_row_count=checked_row_count,
            failed_row_count=len(missing_codes),
            file_path=stock_basic_path,
            extra_metadata={
                "seed_row_count": len(seed_rows),
                "seed_latest_code_count": len(seed_latest_codes),
                "missing_seed_latest_code_samples": missing_codes[:10],
            },
        ),
    )


def _enum_check(
    *,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    field_name: str,
    allowed_values: tuple[str, ...],
) -> dg.AssetCheckResult:
    path = silver_stock_identity_map_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    with connect_configured_duckdb() as connection:
        rows = connection.execute(
            f"""
            SELECT {field_name}, count(*) AS row_count
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE {field_name} NOT IN {allowed_values}
               OR {field_name} IS NULL
               OR trim({field_name}) = ''
            GROUP BY {field_name}
            ORDER BY row_count DESC, {field_name}
            LIMIT 10
            """
        ).fetchall()
        failed_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM {read_parquet(path, hive_partitioning=False)}
                WHERE {field_name} NOT IN {allowed_values}
                   OR {field_name} IS NULL
                   OR trim({field_name}) = ''
                """
            ).fetchone()[0]
        )
        checked_row_count = _row_count(connection, path)
    return dg.AssetCheckResult(
        passed=failed_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            checked_row_count=checked_row_count,
            failed_row_count=failed_count,
            file_path=path,
            extra_metadata={
                "field_name": field_name,
                "allowed_values": list(allowed_values),
                "invalid_value_samples": _sample_dicts(
                    [field_name, "row_count"],
                    rows,
                ),
            },
        ),
    )


@dg.asset_check(asset=silver_stock_identity_map, blocking=True)
def silver_stock_identity_map_contract_check(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        check_scope=CheckScope.SCHEMA,
        rule_results=(
            (
                "silver_stock_identity_map_file_exists",
                silver_stock_identity_map_file_exists(lake_root),
            ),
            (
                "silver_stock_identity_map_row_count_positive",
                silver_stock_identity_map_row_count_positive(lake_root, duckdb),
            ),
            (
                "silver_stock_identity_map_schema_matches_contract",
                silver_stock_identity_map_schema_matches_contract(lake_root, duckdb),
            ),
            (
                "silver_stock_identity_map_source_ts_code_present",
                silver_stock_identity_map_source_ts_code_present(lake_root, duckdb),
            ),
            (
                "silver_stock_identity_map_latest_ts_code_present",
                silver_stock_identity_map_latest_ts_code_present(lake_root, duckdb),
            ),
        ),
    )


@dg.asset_check(asset=silver_stock_identity_map, blocking=True)
def silver_stock_identity_map_key_integrity_check(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        check_scope=CheckScope.KEY_UNIQUENESS,
        rule_results=(
            (
                "silver_stock_identity_map_source_ts_code_unique",
                silver_stock_identity_map_source_ts_code_unique(lake_root, duckdb),
            ),
            (
                "silver_stock_identity_map_conflicting_mapping_absent",
                silver_stock_identity_map_conflicting_mapping_absent(lake_root, duckdb),
            ),
        ),
    )


@dg.asset_check(
    asset=silver_stock_identity_map,
    additional_deps=[silver_stock_basic],
    blocking=True,
)
def silver_stock_identity_map_reference_domain_check(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        check_scope=CheckScope.REFERENTIAL_INTEGRITY,
        rule_results=(
            (
                "silver_stock_identity_map_latest_code_exists_in_stock_basic",
                silver_stock_identity_map_latest_code_exists_in_stock_basic(
                    lake_root, duckdb
                ),
            ),
            (
                "silver_stock_identity_map_seed_latest_code_explainable",
                silver_stock_identity_map_seed_latest_code_explainable(
                    lake_root, duckdb
                ),
            ),
            (
                "silver_stock_identity_map_known_identity_source",
                silver_stock_identity_map_known_identity_source(lake_root, duckdb),
            ),
            (
                "silver_stock_identity_map_known_confidence",
                silver_stock_identity_map_known_confidence(lake_root, duckdb),
            ),
            (
                "silver_stock_identity_map_date_ranges_valid",
                silver_stock_identity_map_date_ranges_valid(lake_root, duckdb),
            ),
        ),
    )
