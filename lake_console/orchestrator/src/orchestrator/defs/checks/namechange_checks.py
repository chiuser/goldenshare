from collections.abc import Sequence
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.assets.namechange import (
    NAMECHANGE_RAW_COLUMN_TYPES,
    NAMECHANGE_SILVER_COLUMN_TYPES,
    raw_tushare_namechange,
    silver_namechange,
)
from orchestrator.defs.duckdb_sql import (
    NAMECHANGE_RAW_REQUIRED_COLUMNS,
    NAMECHANGE_SILVER_REQUIRED_COLUMNS,
    count_parquet_query,
    describe_parquet_query,
    read_parquet,
)
from orchestrator.defs.namechange_timeline import analyze_namechange_silver_rows
from orchestrator.defs.paths import raw_namechange_path, silver_namechange_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata


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
    columns: Sequence[str], rows: Sequence[Sequence[Any]]
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
            extra_metadata={"missing_file": True},
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
                "rule_passed": {
                    rule_name: bool(result.passed)
                    for rule_name, result in rule_results
                },
                "failed_rule_names": failed_rule_names,
            },
        ),
    )


def _schema_result(
    *,
    path: Path,
    observed_schema: dict[str, str],
    expected_schema: dict[str, str],
    checked_row_count: int,
) -> dg.AssetCheckResult:
    missing_columns = [
        column for column in expected_schema if column not in observed_schema
    ]
    extra_columns = [
        column for column in observed_schema if column not in expected_schema
    ]
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


def _read_silver_rows(connection, path: Path) -> list[dict[str, Any]]:
    columns = tuple(NAMECHANGE_SILVER_REQUIRED_COLUMNS)
    rows = connection.execute(
        f"""
        SELECT {", ".join(columns)}
        FROM {read_parquet(path, hive_partitioning=False)}
        """
    ).fetchall()
    return [dict(zip(columns, row, strict=True)) for row in rows]


def raw_namechange_file_exists(lake_root: LakeRootResource) -> dg.AssetCheckResult:
    path = raw_namechange_path(lake_root.root())
    return dg.AssetCheckResult(
        passed=path.exists(),
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            file_path=path,
            extra_metadata={"exists": path.exists()},
        ),
    )


def raw_namechange_row_count_positive(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_namechange_path(lake_root.root())
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


def raw_namechange_required_columns(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_namechange_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    with connect_configured_duckdb() as connection:
        observed_columns = _column_names(connection, path)
        checked_row_count = _row_count(connection, path)
    missing_columns = [
        column for column in NAMECHANGE_RAW_REQUIRED_COLUMNS if column not in observed_columns
    ]
    extra_columns = [
        column for column in observed_columns if column not in NAMECHANGE_RAW_REQUIRED_COLUMNS
    ]
    return dg.AssetCheckResult(
        passed=not missing_columns and not extra_columns,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            checked_row_count=checked_row_count,
            file_path=path,
            extra_metadata={
                "observed_columns": observed_columns,
                "required_columns": list(NAMECHANGE_RAW_REQUIRED_COLUMNS),
                "missing_columns": missing_columns,
                "extra_columns": extra_columns,
            },
        ),
    )


def raw_namechange_schema_matches_tushare_contract(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_namechange_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    with connect_configured_duckdb() as connection:
        observed_schema = _describe_schema(connection, path)
        checked_row_count = _row_count(connection, path)
    return _schema_result(
        path=path,
        observed_schema=observed_schema,
        expected_schema=NAMECHANGE_RAW_COLUMN_TYPES,
        checked_row_count=checked_row_count,
    )


def raw_namechange_required_fields_non_null(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_namechange_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    required_fields = ("ts_code", "name", "start_date", "change_reason")
    condition = " OR ".join(
        f"{field} IS NULL OR trim(CAST({field} AS VARCHAR)) = ''"
        for field in required_fields
    )
    with connect_configured_duckdb() as connection:
        missing_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM {read_parquet(path, hive_partitioning=False)}
                WHERE {condition}
                """
            ).fetchone()[0]
        )
        rows = connection.execute(
            f"""
            SELECT {", ".join(NAMECHANGE_RAW_REQUIRED_COLUMNS)}
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE {condition}
            LIMIT 10
            """
        ).fetchall()
    return dg.AssetCheckResult(
        passed=missing_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            failed_row_count=missing_count,
            file_path=path,
            extra_metadata={
                "required_non_null_fields": list(required_fields),
                "sample_rows": _sample_dicts(NAMECHANGE_RAW_REQUIRED_COLUMNS, rows),
            },
        ),
    )


def raw_namechange_date_string_format_valid(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_namechange_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    with connect_configured_duckdb() as connection:
        invalid_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM {read_parquet(path, hive_partitioning=False)}
                WHERE NOT regexp_matches(CAST(start_date AS VARCHAR), '^\\d{{8}}$')
                   OR (
                     end_date IS NOT NULL
                     AND trim(CAST(end_date AS VARCHAR)) != ''
                     AND NOT regexp_matches(CAST(end_date AS VARCHAR), '^\\d{{8}}$')
                   )
                   OR (
                     ann_date IS NOT NULL
                     AND trim(CAST(ann_date AS VARCHAR)) != ''
                     AND NOT regexp_matches(CAST(ann_date AS VARCHAR), '^\\d{{8}}$')
                   )
                """
            ).fetchone()[0]
        )
        rows = connection.execute(
            f"""
            SELECT ts_code, name, start_date, end_date, ann_date, change_reason
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE NOT regexp_matches(CAST(start_date AS VARCHAR), '^\\d{{8}}$')
               OR (
                 end_date IS NOT NULL
                 AND trim(CAST(end_date AS VARCHAR)) != ''
                 AND NOT regexp_matches(CAST(end_date AS VARCHAR), '^\\d{{8}}$')
               )
               OR (
                 ann_date IS NOT NULL
                 AND trim(CAST(ann_date AS VARCHAR)) != ''
                 AND NOT regexp_matches(CAST(ann_date AS VARCHAR), '^\\d{{8}}$')
               )
            LIMIT 10
            """
        ).fetchall()
    return dg.AssetCheckResult(
        passed=invalid_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            failed_row_count=invalid_count,
            file_path=path,
            extra_metadata={
                "expected_date_format": "YYYYMMDD",
                "sample_rows": _sample_dicts(NAMECHANGE_RAW_REQUIRED_COLUMNS, rows),
            },
        ),
    )


def raw_namechange_exact_duplicate_absent(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_namechange_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    group_columns = ", ".join(NAMECHANGE_RAW_REQUIRED_COLUMNS)
    with connect_configured_duckdb() as connection:
        duplicate_sql = f"""
        SELECT {group_columns}, count(*) AS duplicate_row_count
        FROM {read_parquet(path, hive_partitioning=False)}
        GROUP BY {group_columns}
        HAVING count(*) > 1
        """
        duplicate_key_count = int(
            connection.execute(
                f"SELECT count(*) FROM ({duplicate_sql}) duplicate_keys"
            ).fetchone()[0]
        )
        rows = connection.execute(f"{duplicate_sql} LIMIT 10").fetchall()
    return dg.AssetCheckResult(
        passed=duplicate_key_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.KEY_UNIQUENESS,
            failed_row_count=duplicate_key_count,
            file_path=path,
            extra_metadata={
                "duplicate_sample_rows": _sample_dicts(
                    (*NAMECHANGE_RAW_REQUIRED_COLUMNS, "duplicate_row_count"), rows
                )
            },
        ),
    )


def raw_namechange_multi_open_interval_observed(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_namechange_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    with connect_configured_duckdb() as connection:
        multi_open_sql = f"""
        SELECT ts_code, count(*) AS open_interval_count
        FROM {read_parquet(path, hive_partitioning=False)}
        WHERE end_date IS NULL OR trim(CAST(end_date AS VARCHAR)) = ''
        GROUP BY ts_code
        HAVING count(*) > 1
        """
        code_count = int(
            connection.execute(
                f"SELECT count(*) FROM ({multi_open_sql}) multi_open"
            ).fetchone()[0]
        )
        rows = connection.execute(
            f"{multi_open_sql} ORDER BY open_interval_count DESC, ts_code LIMIT 10"
        ).fetchall()
    return dg.AssetCheckResult(
        passed=True,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            file_path=path,
            extra_metadata={
                "multi_open_code_count": code_count,
                "sample_codes": _sample_dicts(
                    ("ts_code", "open_interval_count"), rows
                ),
            },
        ),
    )


def raw_namechange_overlap_interval_observed(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_namechange_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    with connect_configured_duckdb() as connection:
        overlap_sql = f"""
        WITH normalized AS (
          SELECT
            row_number() OVER () AS row_id,
            ts_code,
            name,
            CASE
              WHEN regexp_matches(CAST(start_date AS VARCHAR), '^\\d{{8}}$')
              THEN strptime(CAST(start_date AS VARCHAR), '%Y%m%d')::DATE
            END AS start_dt,
            CASE
              WHEN end_date IS NULL OR trim(CAST(end_date AS VARCHAR)) = ''
              THEN DATE '9999-12-31'
              WHEN regexp_matches(CAST(end_date AS VARCHAR), '^\\d{{8}}$')
              THEN strptime(CAST(end_date AS VARCHAR), '%Y%m%d')::DATE
            END AS end_dt
          FROM {read_parquet(path, hive_partitioning=False)}
        ),
        overlap_pairs AS (
          SELECT
            a.ts_code,
            a.name AS left_name,
            a.start_dt AS left_start_date,
            a.end_dt AS left_end_date,
            b.name AS right_name,
            b.start_dt AS right_start_date,
            b.end_dt AS right_end_date
          FROM normalized a
          INNER JOIN normalized b
            ON a.ts_code = b.ts_code
           AND a.row_id < b.row_id
           AND a.start_dt IS NOT NULL
           AND b.start_dt IS NOT NULL
           AND a.start_dt <= b.end_dt
           AND b.start_dt <= a.end_dt
        )
        SELECT *
        FROM overlap_pairs
        """
        overlap_count = int(
            connection.execute(
                f"SELECT count(*) FROM ({overlap_sql}) overlap_rows"
            ).fetchone()[0]
        )
        rows = connection.execute(
            f"{overlap_sql} ORDER BY ts_code, left_start_date LIMIT 10"
        ).fetchall()
    return dg.AssetCheckResult(
        passed=True,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            file_path=path,
            extra_metadata={
                "raw_overlap_pair_count": overlap_count,
                "sample_pairs": _sample_dicts(
                    (
                        "ts_code",
                        "left_name",
                        "left_start_date",
                        "left_end_date",
                        "right_name",
                        "right_start_date",
                        "right_end_date",
                    ),
                    rows,
                ),
            },
        ),
    )


def raw_namechange_reason_distribution_observed(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = raw_namechange_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    with connect_configured_duckdb() as connection:
        rows = connection.execute(
            f"""
            SELECT change_reason, count(*) AS checked_row_count
            FROM {read_parquet(path, hive_partitioning=False)}
            GROUP BY change_reason
            ORDER BY checked_row_count DESC, change_reason
            """
        ).fetchall()
    return dg.AssetCheckResult(
        passed=True,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            file_path=path,
            extra_metadata={
                "change_reason_distribution": _sample_dicts(
                    ("change_reason", "checked_row_count"), rows
                )
            },
        ),
    )


def silver_namechange_file_exists(lake_root: LakeRootResource) -> dg.AssetCheckResult:
    path = silver_namechange_path(lake_root.root())
    return dg.AssetCheckResult(
        passed=path.exists(),
        metadata=build_check_metadata(
            check_scope=CheckScope.FILE_EXISTS,
            file_path=path,
            extra_metadata={"exists": path.exists()},
        ),
    )


def silver_namechange_row_count_positive(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_namechange_path(lake_root.root())
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


def silver_namechange_required_columns(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_namechange_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    with connect_configured_duckdb() as connection:
        observed_columns = _column_names(connection, path)
        checked_row_count = _row_count(connection, path)
    missing_columns = [
        column
        for column in NAMECHANGE_SILVER_REQUIRED_COLUMNS
        if column not in observed_columns
    ]
    extra_columns = [
        column
        for column in observed_columns
        if column not in NAMECHANGE_SILVER_REQUIRED_COLUMNS
    ]
    return dg.AssetCheckResult(
        passed=not missing_columns and not extra_columns,
        metadata=build_check_metadata(
            check_scope=CheckScope.SCHEMA,
            checked_row_count=checked_row_count,
            file_path=path,
            extra_metadata={
                "observed_columns": observed_columns,
                "required_columns": list(NAMECHANGE_SILVER_REQUIRED_COLUMNS),
                "missing_columns": missing_columns,
                "extra_columns": extra_columns,
            },
        ),
    )


def silver_namechange_schema_matches_contract(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_namechange_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    with connect_configured_duckdb() as connection:
        observed_schema = _describe_schema(connection, path)
        checked_row_count = _row_count(connection, path)
    return _schema_result(
        path=path,
        observed_schema=observed_schema,
        expected_schema=NAMECHANGE_SILVER_COLUMN_TYPES,
        checked_row_count=checked_row_count,
    )


def silver_namechange_required_fields_non_null(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_namechange_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    required_fields = ("ts_code", "name", "start_date", "change_reason")
    condition = " OR ".join(f"{field} IS NULL" for field in required_fields)
    with connect_configured_duckdb() as connection:
        missing_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM {read_parquet(path, hive_partitioning=False)}
                WHERE {condition}
                   OR trim(ts_code) = ''
                   OR trim(name) = ''
                   OR trim(change_reason) = ''
                """
            ).fetchone()[0]
        )
        rows = connection.execute(
            f"""
            SELECT {", ".join(NAMECHANGE_SILVER_REQUIRED_COLUMNS)}
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE {condition}
               OR trim(ts_code) = ''
               OR trim(name) = ''
               OR trim(change_reason) = ''
            LIMIT 10
            """
        ).fetchall()
    return dg.AssetCheckResult(
        passed=missing_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            failed_row_count=missing_count,
            file_path=path,
            extra_metadata={
                "required_non_null_fields": list(required_fields),
                "sample_rows": _sample_dicts(NAMECHANGE_SILVER_REQUIRED_COLUMNS, rows),
            },
        ),
    )


def silver_namechange_date_order_valid(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_namechange_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    with connect_configured_duckdb() as connection:
        invalid_count = int(
            connection.execute(
                f"""
                SELECT count(*)
                FROM {read_parquet(path, hive_partitioning=False)}
                WHERE end_date IS NOT NULL
                  AND end_date < start_date
                """
            ).fetchone()[0]
        )
        rows = connection.execute(
            f"""
            SELECT ts_code, name, start_date, end_date, ann_date, change_reason
            FROM {read_parquet(path, hive_partitioning=False)}
            WHERE end_date IS NOT NULL
              AND end_date < start_date
            LIMIT 10
            """
        ).fetchall()
    return dg.AssetCheckResult(
        passed=invalid_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            failed_row_count=invalid_count,
            file_path=path,
            extra_metadata={
                "sample_rows": _sample_dicts(NAMECHANGE_SILVER_REQUIRED_COLUMNS, rows)
            },
        ),
    )


def silver_namechange_exact_duplicate_absent(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_namechange_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    group_columns = ", ".join(NAMECHANGE_SILVER_REQUIRED_COLUMNS)
    with connect_configured_duckdb() as connection:
        duplicate_sql = f"""
        SELECT {group_columns}, count(*) AS duplicate_row_count
        FROM {read_parquet(path, hive_partitioning=False)}
        GROUP BY {group_columns}
        HAVING count(*) > 1
        """
        duplicate_key_count = int(
            connection.execute(
                f"SELECT count(*) FROM ({duplicate_sql}) duplicate_keys"
            ).fetchone()[0]
        )
        rows = connection.execute(f"{duplicate_sql} LIMIT 10").fetchall()
    return dg.AssetCheckResult(
        passed=duplicate_key_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.KEY_UNIQUENESS,
            failed_row_count=duplicate_key_count,
            file_path=path,
            extra_metadata={
                "duplicate_sample_rows": _sample_dicts(
                    (*NAMECHANGE_SILVER_REQUIRED_COLUMNS, "duplicate_row_count"), rows
                )
            },
        ),
    )


def silver_namechange_current_open_interval_unique(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_namechange_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    with connect_configured_duckdb() as connection:
        multi_open_sql = f"""
        SELECT ts_code, count(*) AS open_interval_count
        FROM {read_parquet(path, hive_partitioning=False)}
        WHERE end_date IS NULL
        GROUP BY ts_code
        HAVING count(*) > 1
        """
        code_count = int(
            connection.execute(
                f"SELECT count(*) FROM ({multi_open_sql}) multi_open"
            ).fetchone()[0]
        )
        rows = connection.execute(f"{multi_open_sql} LIMIT 10").fetchall()
    return dg.AssetCheckResult(
        passed=code_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.KEY_UNIQUENESS,
            failed_row_count=code_count,
            file_path=path,
            extra_metadata={
                "sample_codes": _sample_dicts(
                    ("ts_code", "open_interval_count"), rows
                )
            },
        ),
    )


def silver_namechange_interval_overlap_absent(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_namechange_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    with connect_configured_duckdb() as connection:
        rows_dicts = _read_silver_rows(connection, path)
    status = analyze_namechange_silver_rows(rows_dicts)
    overlap_count = int(status["overlap_count"])
    return dg.AssetCheckResult(
        passed=overlap_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            failed_row_count=overlap_count,
            file_path=path,
            extra_metadata={"overlap_samples": status["overlap_samples"]},
        ),
    )


def silver_namechange_unknown_adjacent_gap_absent(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    path = silver_namechange_path(lake_root.root())
    if not path.exists():
        return _missing_file_result(path)
    with connect_configured_duckdb() as connection:
        rows_dicts = _read_silver_rows(connection, path)
    status = analyze_namechange_silver_rows(rows_dicts)
    unknown_gap_count = int(status["unknown_adjacent_gap_count"])
    return dg.AssetCheckResult(
        passed=unknown_gap_count == 0,
        metadata=build_check_metadata(
            check_scope=CheckScope.VALUE_SANITY,
            failed_row_count=unknown_gap_count,
            file_path=path,
            extra_metadata={
                "adjacent_gap_count": status["adjacent_gap_count"],
                "known_adjacent_gap_count": status["known_adjacent_gap_count"],
                "unknown_adjacent_gap_samples": status[
                    "unknown_adjacent_gap_samples"
                ],
            },
        ),
    )


@dg.asset_check(asset=raw_tushare_namechange, blocking=True)
def raw_namechange_contract_check(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        check_scope=CheckScope.SCHEMA,
        rule_results=(
            ("raw_namechange_file_exists", raw_namechange_file_exists(lake_root)),
            (
                "raw_namechange_row_count_positive",
                raw_namechange_row_count_positive(lake_root, duckdb),
            ),
            (
                "raw_namechange_required_columns",
                raw_namechange_required_columns(lake_root, duckdb),
            ),
            (
                "raw_namechange_schema_matches_tushare_contract",
                raw_namechange_schema_matches_tushare_contract(lake_root, duckdb),
            ),
            (
                "raw_namechange_required_fields_non_null",
                raw_namechange_required_fields_non_null(lake_root, duckdb),
            ),
        ),
    )


@dg.asset_check(asset=raw_tushare_namechange, blocking=True)
def raw_namechange_key_integrity_check(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return raw_namechange_exact_duplicate_absent(lake_root, duckdb)


@dg.asset_check(asset=raw_tushare_namechange, blocking=True)
def raw_namechange_date_domain_check(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return raw_namechange_date_string_format_valid(lake_root, duckdb)


@dg.asset_check(asset=silver_namechange, blocking=True)
def silver_namechange_contract_check(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        check_scope=CheckScope.SCHEMA,
        rule_results=(
            ("silver_namechange_file_exists", silver_namechange_file_exists(lake_root)),
            (
                "silver_namechange_row_count_positive",
                silver_namechange_row_count_positive(lake_root, duckdb),
            ),
            (
                "silver_namechange_required_columns",
                silver_namechange_required_columns(lake_root, duckdb),
            ),
            (
                "silver_namechange_schema_matches_contract",
                silver_namechange_schema_matches_contract(lake_root, duckdb),
            ),
            (
                "silver_namechange_required_fields_non_null",
                silver_namechange_required_fields_non_null(lake_root, duckdb),
            ),
        ),
    )


@dg.asset_check(asset=silver_namechange, blocking=True)
def silver_namechange_key_integrity_check(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        check_scope=CheckScope.KEY_UNIQUENESS,
        rule_results=(
            (
                "silver_namechange_exact_duplicate_absent",
                silver_namechange_exact_duplicate_absent(lake_root, duckdb),
            ),
            (
                "silver_namechange_current_open_interval_unique",
                silver_namechange_current_open_interval_unique(lake_root, duckdb),
            ),
        ),
    )


@dg.asset_check(asset=silver_namechange, blocking=True)
def silver_namechange_interval_domain_check(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    return _combined_check_result(
        check_scope=CheckScope.VALUE_SANITY,
        rule_results=(
            (
                "silver_namechange_date_order_valid",
                silver_namechange_date_order_valid(lake_root, duckdb),
            ),
            (
                "silver_namechange_interval_overlap_absent",
                silver_namechange_interval_overlap_absent(lake_root, duckdb),
            ),
            (
                "silver_namechange_unknown_adjacent_gap_absent",
                silver_namechange_unknown_adjacent_gap_absent(lake_root, duckdb),
            ),
        ),
    )
