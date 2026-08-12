"""Bounded same-day relation predicates shared by checks and readiness scans."""

from __future__ import annotations

from pathlib import Path

from orchestrator.defs.duckdb_sql import read_parquet


def _relation_failure(
    connection,
    *,
    source_path: Path,
    index_path: Path,
    mode: str,
) -> tuple[int, tuple[dict[str, object], ...]]:
    if not index_path.exists():
        return 1, ({"reason_code": "index_partition_missing", "path": str(index_path)},)
    source_relation = read_parquet(source_path, hive_partitioning=False)
    index_relation = read_parquet(index_path, hive_partitioning=False)
    if mode == "index_subset_daily":
        sql = f"""
        WITH source_codes AS (SELECT DISTINCT ts_code FROM {source_relation}),
        index_codes AS (SELECT DISTINCT ts_code FROM {index_relation}),
        index_only AS (
            SELECT ts_code FROM index_codes
            EXCEPT
            SELECT ts_code FROM source_codes
        )
        SELECT count(*) FROM index_only
        """
        sample_sql = f"""
        WITH source_codes AS (SELECT DISTINCT ts_code FROM {source_relation}),
        index_codes AS (SELECT DISTINCT ts_code FROM {index_relation}),
        index_only AS (
            SELECT ts_code FROM index_codes EXCEPT SELECT ts_code FROM source_codes
        )
        SELECT ts_code, 'index_code_missing_from_daily' AS reason_code FROM index_only
        LIMIT 5
        """
    elif mode == "member_subset_index":
        sql = f"""
        SELECT count(*) FROM (
            SELECT DISTINCT ts_code FROM {source_relation}
            EXCEPT
            SELECT DISTINCT ts_code FROM {index_relation}
        )
        """
        sample_sql = f"""
        SELECT ts_code, 'member_code_not_in_index' AS reason_code
        FROM (
            SELECT DISTINCT ts_code FROM {source_relation}
            EXCEPT
            SELECT DISTINCT ts_code FROM {index_relation}
        )
        LIMIT 5
        """
    else:
        raise ValueError(f"unknown board relation mode: {mode}")
    failure_count = int(connection.execute(sql).fetchone()[0])
    rows = connection.execute(sample_sql).fetchall() if failure_count else ()
    return failure_count, tuple(
        {"ts_code": row[0], "reason_code": row[1]} for row in rows
    )


def audit_raw_board_relation(
    connection,
    *,
    source_path: Path,
    index_path: Path,
    mode: str,
) -> tuple[int, tuple[dict[str, object], ...]]:
    return _relation_failure(
        connection,
        source_path=source_path,
        index_path=index_path,
        mode=mode,
    )


def audit_silver_board_relation(
    connection,
    *,
    source_path: Path,
    index_path: Path,
    mode: str,
) -> tuple[int, tuple[dict[str, object], ...]]:
    return _relation_failure(
        connection,
        source_path=source_path,
        index_path=index_path,
        mode=mode,
    )


__all__ = ["audit_raw_board_relation", "audit_silver_board_relation"]
