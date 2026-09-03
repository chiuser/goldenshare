"""Read ETF daily Raw once per asset/year for historical evidence."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from time import perf_counter
from typing import Any

from orchestrator.defs.duckdb_sql import duckdb_string
from orchestrator.defs.io.etf_daily_raw_writer import (
    FUND_ADJ_RAW_SPEC,
    FUND_DAILY_RAW_SPEC,
    EtfDailyRawSpec,
    etf_daily_raw_content_hash_sql,
)
from orchestrator.defs.io.etf_daily_silver_writer import (
    FUND_ADJ_SILVER_SPEC,
    FUND_DAILY_SILVER_SPEC,
    etf_daily_domain_predicates,
)
from orchestrator.defs.run_contracts.etf_daily import (
    ETF_DAILY_DIAGNOSTIC_SAMPLE_LIMIT,
    normalize_etf_daily_trade_date,
)

_ROWS = "etf_daily_bootstrap_raw_rows"
_COVERAGE = "etf_daily_bootstrap_raw_coverage"


def etf_daily_raw_batches(
    trade_dates: Sequence[str],
) -> Iterator[tuple[EtfDailyRawSpec, tuple[str, ...]]]:
    dates = tuple(normalize_etf_daily_trade_date(value) for value in trade_dates)
    if not dates or dates != tuple(sorted(set(dates))):
        raise ValueError("Raw batch dates must be nonempty, unique and sorted")
    for spec in (FUND_DAILY_RAW_SPEC, FUND_ADJ_RAW_SPEC):
        for year in sorted({value[:4] for value in dates}):
            yield spec, tuple(value for value in dates if value.startswith(year))


def audit_etf_daily_raw_batch(
    connection: Any,
    *,
    lake_root: Path,
    trade_dates: Sequence[str],
    spec: EtfDailyRawSpec,
    basic_relation_sql: str | None = None,
) -> dict[str, Any]:
    """Return bounded partition summaries; never fetch Raw detail into Python."""
    if spec is not FUND_DAILY_RAW_SPEC and spec is not FUND_ADJ_RAW_SPEC:
        raise ValueError("Raw batch requires an approved ETF daily spec")
    dates = tuple(normalize_etf_daily_trade_date(value) for value in trade_dates)
    if (
        not dates
        or dates != tuple(sorted(set(dates)))
        or len({value[:4] for value in dates}) != 1
    ):
        raise ValueError("Raw batch requires unique sorted dates from one year")
    paths = {value: spec.target_path_builder(lake_root, value) for value in dates}
    for path in paths.values():
        if not path.is_file():
            raise ValueError(f"Raw manifest file is missing: {path}")
    started = perf_counter()
    query_count = 0

    def query(sql: str):
        nonlocal query_count
        query_count += 1
        return connection.execute(sql)

    path_sql = "[" + ", ".join(duckdb_string(path) for path in paths.values()) + "]"
    schemas = query(f"""
        SELECT file_name, list(name ORDER BY column_id),
               list(upper(duckdb_type) ORDER BY column_id)
        FROM parquet_schema({path_sql}) WHERE column_id > 0
        GROUP BY file_name
    """).fetchall()
    expected_types = tuple(spec.raw_column_types[name] for name in spec.source_columns)
    if {row[0] for row in schemas} != {str(path) for path in paths.values()}:
        raise ValueError("Raw batch schema file set does not match frozen paths")
    for file_name, columns, types in schemas:
        if tuple(columns) != spec.source_columns or tuple(types) != expected_types:
            raise ValueError(
                f"Raw manifest file is invalid: schema_columns/schema_types: {file_name}"
            )

    expected_sql = ", ".join(
        f"({duckdb_string(path)}, {duckdb_string(value)})"
        for value, path in paths.items()
    )
    projection = ", ".join(f'raw_rows."{name}"' for name in spec.source_columns)
    files: list[dict[str, Any]] = []
    domains: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    created_tables: list[str] = []
    try:
        query(f"""
            CREATE TEMP TABLE {_ROWS} AS
            SELECT {projection}, raw_rows.filename AS __raw_file,
                   expected.partition_date AS __partition_date
            FROM read_parquet({path_sql}, hive_partitioning=false,
                              union_by_name=false, filename=true) raw_rows
            JOIN (VALUES {expected_sql}) expected(file_path, partition_date)
              ON raw_rows.filename = expected.file_path
        """)
        created_tables.append(_ROWS)
        metrics = query(f"""
            SELECT __partition_date, count(*),
              count(*) FILTER (WHERE ts_code IS NULL OR trim(ts_code) = ''
                OR trade_date IS NULL OR trim(trade_date) = ''),
              count(*) - count(DISTINCT (ts_code, trade_date)),
              count(*) FILTER (WHERE trade_date IS NULL OR trim(trade_date) = ''
                OR trade_date != replace(__partition_date, '-', '')),
              {etf_daily_raw_content_hash_sql(spec)}
            FROM {_ROWS} GROUP BY __partition_date
        """).fetchall()
        by_date = {row[0]: row[1:] for row in metrics}
        for value, path in paths.items():
            row = by_date.get(value)
            if row is None:
                raise ValueError(
                    f"Raw manifest file is invalid: empty_partition: {path}"
                )
            errors = [
                name
                for name, count in zip(
                    ("invalid_key", "duplicate_key", "partition_date"),
                    row[1:4],
                    strict=True,
                )
                if count
            ]
            if errors:
                raise ValueError(
                    f"Raw manifest file is invalid: {path}, errors={errors!r}"
                )
            files.append(
                {
                    "asset_key": spec.asset_key,
                    "trade_date": value,
                    "target_path": str(path),
                    "row_count": int(row[0]),
                    "content_hash": str(row[4]),
                    "size_bytes": path.stat().st_size,
                    "error_codes": [],
                }
            )
        if basic_relation_sql is not None:
            silver_spec = (
                FUND_DAILY_SILVER_SPEC
                if spec is FUND_DAILY_RAW_SPEC
                else FUND_ADJ_SILVER_SPEC
            )
            predicates = etf_daily_domain_predicates(silver_spec)
            count_sql = ", ".join(
                f"count(*) FILTER (WHERE {sql})" for sql in predicates.values()
            )
            any_failure = " OR ".join(f"({sql})" for sql in predicates.values())
            domain_counts = query(f"""
                SELECT __partition_date, count(*), {count_sql},
                       count(*) FILTER (WHERE {any_failure})
                FROM {_ROWS} GROUP BY __partition_date
            """).fetchall()
            failure_sql = " UNION ALL ".join(
                f"SELECT __partition_date, {duckdb_string(name)} AS reason_code, ts_code, trade_date "
                f"FROM {_ROWS} WHERE {sql}"
                for name, sql in predicates.items()
            )
            domain_samples = query(f"""
                SELECT * FROM ({failure_sql}) failures
                QUALIFY row_number() OVER (
                  PARTITION BY __partition_date ORDER BY reason_code, ts_code, trade_date
                ) <= {ETF_DAILY_DIAGNOSTIC_SAMPLE_LIMIT}
                ORDER BY __partition_date, reason_code, ts_code, trade_date
            """).fetchall()
            samples_by_date: dict[str, list[dict[str, Any]]] = {}
            for value, reason, code, trade_date in domain_samples:
                samples_by_date.setdefault(value, []).append(
                    {
                        "reason_code": reason,
                        "ts_code": code,
                        "trade_date": str(trade_date),
                    }
                )
            for row in domain_counts:
                domains.append(
                    {
                        "asset_key": spec.asset_key,
                        "trade_date": row[0],
                        "checked_row_count": int(row[1]),
                        "failed_row_count": int(row[-1]),
                        "failure_counts": dict(
                            zip(predicates, map(int, row[2:-1]), strict=True)
                        ),
                        "failure_samples": samples_by_date.get(row[0], []),
                    }
                )

            query(f"""
                CREATE TEMP TABLE {_COVERAGE} AS
                WITH expected AS (
                  SELECT dates.__partition_date, basic.ts_code, true AS expected_code
                  FROM (SELECT DISTINCT __partition_date FROM {_ROWS}) dates
                  JOIN {basic_relation_sql} basic
                    ON basic.list_date <= CAST(dates.__partition_date AS DATE)
                  WHERE (ends_with(basic.ts_code, '.SH') OR ends_with(basic.ts_code, '.SZ'))
                    AND basic.exchange = right(basic.ts_code, 2)
                    AND basic.list_status = 'L' AND basic.list_date IS NOT NULL
                ), present AS (
                  SELECT DISTINCT __partition_date, ts_code, true AS present_code FROM {_ROWS}
                )
                SELECT coalesce(expected.__partition_date, present.__partition_date) AS __partition_date,
                       coalesce(expected.ts_code, present.ts_code) AS ts_code,
                       coalesce(expected_code, false) AS expected_code,
                       coalesce(present_code, false) AS present_code
                FROM expected FULL OUTER JOIN present USING (__partition_date, ts_code)
            """)
            created_tables.append(_COVERAGE)
            coverage_counts = query(f"""
                SELECT __partition_date, count(*) FILTER (WHERE expected_code),
                  count(*) FILTER (WHERE present_code),
                  count(*) FILTER (WHERE expected_code AND NOT present_code),
                  count(*) FILTER (WHERE present_code AND NOT expected_code)
                FROM {_COVERAGE} GROUP BY __partition_date
            """).fetchall()
            coverage_samples = query(f"""
                SELECT __partition_date,
                  CASE WHEN expected_code THEN 'MISSING_EXPECTED_CODE' ELSE 'RAW_EXTRA_CODE' END AS reason_code,
                  ts_code
                FROM {_COVERAGE} WHERE expected_code != present_code
                QUALIFY row_number() OVER (
                  PARTITION BY __partition_date ORDER BY reason_code, ts_code
                ) <= {ETF_DAILY_DIAGNOSTIC_SAMPLE_LIMIT}
                ORDER BY __partition_date, reason_code, ts_code
            """).fetchall()
            coverage_samples_by_date: dict[str, list[dict[str, Any]]] = {}
            for value, reason, code in coverage_samples:
                coverage_samples_by_date.setdefault(value, []).append(
                    {"reason_code": reason, "ts_code": code}
                )
            for value, expected, present, missing, extra in coverage_counts:
                coverage.append(
                    {
                        "asset_key": spec.asset_key,
                        "trade_date": value,
                        "expected_code_count": int(expected),
                        "present_code_count": int(present),
                        "missing_expected_code_count": int(missing),
                        "raw_extra_code_count": int(extra),
                        "samples": coverage_samples_by_date.get(value, []),
                    }
                )
        spill_bytes = int(
            query(
                "SELECT coalesce(sum(size), 0) FROM duckdb_temporary_files()"
            ).fetchone()[0]
        )
    finally:
        for table in reversed(created_tables):
            query(f"DROP TABLE {table}")
    return {
        "files": files,
        "domain_profiles": domains,
        "coverage_profiles": coverage,
        "performance": {
            "asset_key": spec.asset_key,
            "year": dates[0][:4],
            "file_count": len(paths),
            "row_count": sum(item["row_count"] for item in files),
            "bytes": sum(item["size_bytes"] for item in files),
            "sql_query_count": query_count,
            "raw_data_load_count": 1,
            "temp_spill_bytes_at_batch_end": spill_bytes,
            "elapsed_ms": round((perf_counter() - started) * 1000, 3),
        },
    }
