"""Reconcile ETF daily Raw/Silver files in bounded dataset/year groups."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter
from typing import Any

from orchestrator.defs.bootstrap.etf_daily_raw_batch_audit import (
    audit_etf_daily_raw_batch,
)
from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.io.etf_daily_silver_writer import (
    FUND_ADJ_SILVER_SPEC,
    FUND_DAILY_SILVER_SPEC,
    EtfDailyCoverageAudit,
    EtfDailySilverSpec,
    EtfDailySourceParityAudit,
    etf_daily_classified_select,
    etf_daily_domain_predicates,
    etf_daily_silver_content_hash_sql,
)
from orchestrator.defs.run_contracts.etf_basic import EtfBasicSilverSnapshotReference
from orchestrator.defs.run_contracts.etf_daily import ETF_DAILY_REJECTION_REASON_CODES

_RAW = "etf_daily_physical_raw"
_SILVER = "etf_daily_physical_silver"


def audit_etf_daily_physical_batch(
    connection: Any,
    *,
    lake_root: Path,
    trade_dates: Sequence[str],
    spec: EtfDailySilverSpec,
    basic_sql: str,
    basic_reference: EtfBasicSilverSnapshotReference,
) -> dict[str, Any]:
    """Read bounded detail in DuckDB and return only per-file evidence to Python."""
    if spec is not FUND_DAILY_SILVER_SPEC and spec is not FUND_ADJ_SILVER_SPEC:
        raise ValueError("Physical batch requires an approved ETF daily spec")
    started = perf_counter()
    raw_batch = audit_etf_daily_raw_batch(
        connection, lake_root=lake_root, trade_dates=trade_dates, spec=spec.raw_spec
    )
    dates = tuple(item["trade_date"] for item in raw_batch["files"])
    paths = {value: spec.target_path_builder(lake_root, value) for value in dates}
    query_count = raw_batch["performance"]["sql_query_count"]

    def query(sql: str):
        nonlocal query_count
        query_count += 1
        return connection.execute(sql)

    path_sql = "[" + ", ".join(duckdb_string(path) for path in paths.values()) + "]"
    schemas = query(f"""
        SELECT file_name, list(name ORDER BY column_id),
               list(upper(duckdb_type) ORDER BY column_id)
        FROM parquet_schema({path_sql}) WHERE column_id > 0 GROUP BY file_name
    """).fetchall()
    expected_types = tuple(
        spec.silver_column_types[name] for name in spec.source_columns
    )
    if {row[0] for row in schemas} != {str(path) for path in paths.values()}:
        raise ValueError("Silver batch schema file set does not match frozen paths")
    for file_name, columns, types in schemas:
        if tuple(columns) != spec.source_columns or tuple(types) != expected_types:
            raise ValueError(
                f"Silver file is invalid: schema_columns/schema_types: {file_name}"
            )

    predicates = etf_daily_domain_predicates(spec)
    created_tables: list[str] = []
    try:
        for table, table_paths, typed_date in (
            (
                _RAW,
                {
                    item["trade_date"]: Path(item["target_path"])
                    for item in raw_batch["files"]
                },
                False,
            ),
            (_SILVER, paths, True),
        ):
            files_sql = (
                "["
                + ", ".join(duckdb_string(path) for path in table_paths.values())
                + "]"
            )
            mapping_sql = ", ".join(
                f"({duckdb_string(path)}, {duckdb_string(value)})"
                for value, path in table_paths.items()
            )
            projection = ", ".join(f'rows."{name}"' for name in spec.source_columns)
            classified = etf_daily_classified_select(
                raw_relation_sql=f"""
                    SELECT {projection}, expected.__partition_date
                    FROM read_parquet({files_sql}, hive_partitioning=false,
                                      union_by_name=false, filename=true) rows
                    JOIN (VALUES {mapping_sql}) expected(file_path, __partition_date)
                      ON rows.filename = expected.file_path
                """,
                basic_relation_sql=basic_sql,
                trade_date_is_typed=typed_date,
            )
            query(f"CREATE TEMP TABLE {table} AS {classified}")
            created_tables.append(table)

        domain_sql = ", ".join(
            f"count(*) FILTER (WHERE {predicate})" for predicate in predicates.values()
        )
        silver_metrics = query(f"""
            SELECT __partition_date, count(*),
              count(*) FILTER (WHERE ts_code IS NULL OR trim(ts_code) = '' OR trade_date IS NULL),
              count(*) - count(DISTINCT (ts_code, trade_date)),
              count(*) FILTER (WHERE trade_date != CAST(__partition_date AS DATE)),
              count(*) FILTER (WHERE rejection_reason IS NOT NULL),
              {domain_sql}, {etf_daily_silver_content_hash_sql(spec)}
            FROM {_SILVER} GROUP BY __partition_date
        """).fetchall()
        silver_by_date = {row[0]: row[1:] for row in silver_metrics}
        reason_sql = ", ".join(
            f"count(*) FILTER (WHERE rejection_reason = {duckdb_string(reason)})"
            for reason in ETF_DAILY_REJECTION_REASON_CODES
        )
        raw_metrics = query(f"""
            SELECT __partition_date, count(*),
              count(*) FILTER (WHERE rejection_reason IS NULL),
              count(*) FILTER (WHERE rejection_reason IS NOT NULL), {reason_sql}
            FROM {_RAW} GROUP BY __partition_date
        """).fetchall()
        raw_by_date = {row[0]: row[1:] for row in raw_metrics}

        columns = ", ".join(f'"{name}"' for name in spec.source_columns)
        trailing = ", ".join(f'"{name}"' for name in spec.source_columns[2:])
        expected_sql = f"""
            SELECT __partition_date, ts_code,
                   strptime(trade_date, '%Y%m%d')::DATE AS trade_date, {trailing}
            FROM {_RAW} WHERE rejection_reason IS NULL
        """
        difference_rows = query(f"""
            WITH expected AS ({expected_sql}), actual AS (
              SELECT __partition_date, {columns} FROM {_SILVER}
            ), differences AS (
              SELECT __partition_date, 'missing' AS direction FROM (
                SELECT * FROM expected EXCEPT ALL SELECT * FROM actual
              ) missing
              UNION ALL
              SELECT __partition_date, 'extra' AS direction FROM (
                SELECT * FROM actual EXCEPT ALL SELECT * FROM expected
              ) extra
            )
            SELECT __partition_date, count(*) FILTER (WHERE direction = 'missing'),
                   count(*) FILTER (WHERE direction = 'extra')
            FROM differences GROUP BY __partition_date
        """).fetchall()
        differences_by_date = {row[0]: row[1:] for row in difference_rows}

        dates_sql = ", ".join(f"({duckdb_string(value)})" for value in dates)
        coverage_rows = query(f"""
            WITH membership AS (
              SELECT dates.__partition_date, basic.ts_code, 'expected' AS kind
              FROM (VALUES {dates_sql}) dates(__partition_date)
              JOIN {basic_sql} basic ON basic.list_date <= CAST(dates.__partition_date AS DATE)
              WHERE (ends_with(basic.ts_code, '.SH') OR ends_with(basic.ts_code, '.SZ'))
                AND basic.exchange = right(basic.ts_code, 2) AND basic.list_status = 'L'
                AND basic.list_date IS NOT NULL
              UNION ALL SELECT __partition_date, ts_code, 'raw' FROM {_RAW}
              UNION ALL SELECT __partition_date, ts_code, 'silver' FROM {_SILVER}
            ), codes AS (
              SELECT __partition_date, ts_code, bool_or(kind = 'expected') AS expected,
                bool_or(kind = 'raw') AS raw_present, bool_or(kind = 'silver') AS silver_present
              FROM membership GROUP BY __partition_date, ts_code
            )
            SELECT __partition_date, count(*) FILTER (WHERE expected),
              count(*) FILTER (WHERE expected AND raw_present),
              count(*) FILTER (WHERE silver_present),
              count(*) FILTER (WHERE expected AND NOT silver_present),
              count(*) FILTER (WHERE raw_present AND NOT expected),
              count(*) FILTER (WHERE silver_present AND NOT expected)
            FROM codes GROUP BY __partition_date
        """).fetchall()
        coverage_by_date = {row[0]: row[1:] for row in coverage_rows}
        spill_bytes = int(
            query(
                "SELECT coalesce(sum(size), 0) FROM duckdb_temporary_files()"
            ).fetchone()[0]
        )
    finally:
        for table in reversed(created_tables):
            query(f"DROP TABLE {table}")

    files: list[dict[str, Any]] = []
    for raw in raw_batch["files"]:
        value = raw["trade_date"]
        silver = silver_by_date.get(
            value, (0,) * (5 + len(predicates)) + (hashlib.sha256(b"").hexdigest(),)
        )
        counts = raw_by_date[value]
        differences = differences_by_date.get(value, (0, 0))
        parity = EtfDailySourceParityAudit(
            raw_row_count=int(counts[0]),
            selected_row_count=int(counts[1]),
            rejected_row_count=int(counts[2]),
            silver_row_count=int(silver[0]),
            reason_counts=dict(
                zip(ETF_DAILY_REJECTION_REASON_CODES, map(int, counts[3:]), strict=True)
            ),
            expected_minus_silver_count=int(differences[0]),
            silver_minus_expected_count=int(differences[1]),
            failure_samples=(),
        )
        coverage = EtfDailyCoverageAudit(
            *map(int, coverage_by_date.get(value, (0,) * 6)), failure_samples=()
        )
        errors = [
            name
            for name, count in zip(
                ("invalid_key", "duplicate_key", "partition_date", "source_filter"),
                silver[1:5],
                strict=True,
            )
            if count
        ]
        errors.extend(parity.error_codes)
        errors.extend(
            name for name, count in zip(predicates, silver[5:-1], strict=True) if count
        )
        if spec is FUND_ADJ_SILVER_SPEC:
            errors.extend(coverage.error_codes)
        files.extend(
            [
                {
                    "asset_key": raw["asset_key"],
                    "trade_date": value,
                    "target_path": raw["target_path"],
                    "row_count": raw["row_count"],
                    "content_hash": raw["content_hash"],
                    "source_row_count": raw["row_count"],
                    "normalized_row_count": raw["row_count"],
                    "written_row_count": raw["row_count"],
                    "source_fields": list(spec.source_columns),
                    "errors": raw["error_codes"],
                    "passed": not raw["error_codes"],
                },
                {
                    "asset_key": spec.asset_key,
                    "trade_date": value,
                    "target_path": str(paths[value]),
                    "row_count": int(silver[0]),
                    "content_hash": str(silver[-1]),
                    "raw_row_count": parity.raw_row_count,
                    "selected_row_count": parity.selected_row_count,
                    "rejected_row_count": parity.rejected_row_count,
                    "written_row_count": int(silver[0]),
                    "reject_reason_counts": dict(parity.reason_counts),
                    "basic_reference": basic_reference.model_dump(mode="json"),
                    "basic_reference_fingerprint": basic_reference.reference_fingerprint,
                    "basic_raw_snapshot_hash": basic_reference.raw_snapshot_hash,
                    "basic_silver_content_hash": basic_reference.silver_content_hash,
                    "basic_raw_uri": basic_reference.raw_uri,
                    "basic_silver_uri": basic_reference.silver_uri,
                    "source_fields": list(spec.source_columns),
                    "coverage_warning": spec is FUND_DAILY_SILVER_SPEC
                    and coverage.has_warning,
                    "coverage_error_codes": list(coverage.error_codes),
                    "missing_expected_code_count": coverage.missing_expected_code_count,
                    "silver_extra_code_count": coverage.silver_extra_code_count,
                    "errors": errors,
                    "passed": not errors,
                },
            ]
        )
    return {
        "files": files,
        "performance": {
            "asset_key": spec.asset_key,
            "year": dates[0][:4],
            "file_count": 2 * len(dates),
            "bytes": raw_batch["performance"]["bytes"]
            + sum(path.stat().st_size for path in paths.values()),
            "sql_query_count": query_count,
            "raw_data_load_count": 2,
            "silver_data_load_count": 1,
            "temp_spill_bytes_at_batch_end": spill_bytes,
            "elapsed_ms": round((perf_counter() - started) * 1000, 3),
        },
    }
