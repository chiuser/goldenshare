"""Formula-free file and source-coverage audit for QFQ nine-turn assets."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import duckdb

from orchestrator.defs.duckdb_sql import (
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import gold_stock_daily_qfq_path
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_NINETURN_SCHEMA,
    GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA,
)
from orchestrator.defs.run_contracts.column_schema import ColumnContract
from orchestrator.defs.run_contracts.qfq_nineturn import (
    QFQ_NINETURN_SIGNAL_THRESHOLD,
    normalize_qfq_nineturn_minute_freq,
)

QFQ_NINETURN_INTEGRITY_RULE_NAMES = (
    "file_contract",
    "partition_alignment",
    "key_integrity",
    "value_domain",
    "source_key_coverage",
    "source_value_consistency",
)
QFQ_NINETURN_FAILURE_SAMPLE_LIMIT = 20


@dataclass(frozen=True, slots=True)
class QfqNineturnIntegrityDiagnostics:
    passed: bool
    checked_row_count: int
    source_row_count: int
    duplicate_key_count: int
    null_key_count: int
    invalid_value_count: int
    missing_source_key_count: int
    extra_output_key_count: int
    source_value_mismatch_count: int
    failed_rule_names: tuple[str, ...]
    failure_samples: tuple[dict[str, object], ...]

    @property
    def failed_row_count(self) -> int:
        return (
            self.duplicate_key_count
            + self.null_key_count
            + self.invalid_value_count
            + self.missing_source_key_count
            + self.extra_output_key_count
            + self.source_value_mismatch_count
        )


def qfq_nineturn_source_paths_for_partition(
    *,
    lake_root: Path,
    partition_key: str,
    freq: int | None,
) -> tuple[Path, ...]:
    if freq is None:
        return (gold_stock_daily_qfq_path(lake_root, partition_key),)
    normalized_freq = normalize_qfq_nineturn_minute_freq(freq)
    source_root = (
        Path(lake_root) / "gold" / "quote" / "stk_mins_qfq" / f"freq={normalized_freq}"
    )
    return tuple(
        sorted(source_root.glob(f"ts_code=*/year={partition_key[:4]}/part-000.parquet"))
    )


def audit_qfq_nineturn_integrity(
    connection: duckdb.DuckDBPyConnection,
    *,
    target_path: Path,
    source_paths: Sequence[Path],
    partition_key: str,
    freq: int | None,
    source_relation: str | None = None,
) -> QfqNineturnIntegrityDiagnostics:
    normalized_freq = None if freq is None else normalize_qfq_nineturn_minute_freq(freq)
    schema = (
        GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA
        if normalized_freq is None
        else GOLD_STK_MINS_QFQ_NINETURN_SCHEMA
    )
    if not target_path.is_file():
        return _failed_file_contract({"failure": "target_file_missing"})
    existing_source_paths = tuple(path for path in source_paths if path.is_file())
    if source_relation is None and not existing_source_paths:
        return _failed_source_coverage({"failure": "source_files_missing"})

    try:
        observed_schema = tuple(
            (str(row[0]), str(row[1]).upper())
            for row in connection.execute(
                describe_parquet_query(target_path, hive_partitioning=False)
            ).fetchall()
        )
    except Exception as error:  # noqa: BLE001 - corrupt parquet is a check result.
        return _failed_file_contract(
            {"failure": "target_parquet_unreadable", "error_type": type(error).__name__}
        )
    expected_schema = _schema_tuple(schema)
    if observed_schema != expected_schema:
        return _failed_file_contract(
            {
                "failure": "schema_mismatch",
                "expected_columns": [name for name, _type in expected_schema],
                "observed_columns": [name for name, _type in observed_schema],
            }
        )

    target = read_parquet(target_path, hive_partitioning=False)
    source = source_relation or _read_parquet_paths(existing_source_paths)
    key_columns = (
        "ts_code, trade_date"
        if normalized_freq is None
        else "ts_code, freq, trade_time"
    )
    null_key_predicate = (
        "ts_code IS NULL OR trim(CAST(ts_code AS VARCHAR)) = '' OR trade_date IS NULL"
        if normalized_freq is None
        else "ts_code IS NULL OR trim(CAST(ts_code AS VARCHAR)) = '' OR "
        "trade_date IS NULL OR freq IS NULL OR trade_time IS NULL"
    )
    partition_predicate = (
        f"trade_date != DATE {duckdb_string(partition_key)}"
        if normalized_freq is None
        else f"trade_date != DATE {duckdb_string(partition_key)} "
        f"OR CAST(trade_time AS DATE) != DATE {duckdb_string(partition_key)} "
        f"OR CAST(freq AS INTEGER) != {normalized_freq}"
    )
    metrics = connection.execute(
        f"""
        SELECT
          count(*) AS row_count,
          count(*) - count(DISTINCT ({key_columns})) AS duplicate_key_count,
          count(*) FILTER (WHERE {null_key_predicate}) AS null_key_count,
          count(*) FILTER (WHERE {partition_predicate}) AS partition_mismatch_count,
          count(*) FILTER (
            WHERE close_qfq IS NULL OR NOT isfinite(close_qfq) OR close_qfq <= 0
              OR up_count IS NULL OR down_count IS NULL
              OR up_count < 0 OR down_count < 0
              OR (up_count > 0 AND down_count > 0)
              OR (nine_up_turn IS NOT NULL AND nine_up_turn != '+9')
              OR (nine_down_turn IS NOT NULL AND nine_down_turn != '-9')
              OR (nine_up_turn = '+9' AND up_count < {QFQ_NINETURN_SIGNAL_THRESHOLD})
              OR (nine_down_turn = '-9' AND down_count < {QFQ_NINETURN_SIGNAL_THRESHOLD})
              OR (nine_up_turn IS NOT NULL AND nine_down_turn IS NOT NULL)
          ) AS invalid_value_count
        FROM {target}
        """
    ).fetchone()
    row_count, duplicate_count, null_count, partition_count, invalid_count = (
        int(value or 0) for value in metrics
    )

    source_identity_sql = _source_identity_sql(
        source=source,
        partition_key=partition_key,
        freq=normalized_freq,
    )
    target_identity_sql = _target_identity_sql(target=target, freq=normalized_freq)
    source_row_count, missing_count, extra_count = (
        int(value or 0)
        for value in connection.execute(
            f"""
            WITH source_keys AS ({source_identity_sql}),
            target_keys AS ({target_identity_sql})
            SELECT
              (SELECT count(*) FROM source_keys),
              (SELECT count(*) FROM (
                SELECT * FROM source_keys EXCEPT SELECT * FROM target_keys
              )),
              (SELECT count(*) FROM (
                SELECT * FROM target_keys EXCEPT SELECT * FROM source_keys
              ))
            """
        ).fetchone()
    )
    source_value_sql = _source_value_sql(
        source=source,
        partition_key=partition_key,
        freq=normalized_freq,
    )
    target_value_sql = _target_value_sql(target=target, freq=normalized_freq)
    value_mismatch_count = int(
        connection.execute(
            f"""
            WITH source_values AS ({source_value_sql}),
            target_values AS ({target_value_sql})
            SELECT count(*)
            FROM source_values source
            INNER JOIN target_values target USING ({key_columns})
            WHERE source.source_key_count != 1
               OR target.close_qfq IS NULL
               OR source.source_close IS NULL
               OR abs(target.close_qfq - source.source_close)
                    > 1e-10 * greatest(1.0, abs(source.source_close))
            """
        ).fetchone()[0]
        or 0
    )
    failed_rules: list[str] = []
    if row_count <= 0:
        failed_rules.append("file_contract")
    if partition_count:
        failed_rules.append("partition_alignment")
    if duplicate_count or null_count:
        failed_rules.append("key_integrity")
    if invalid_count:
        failed_rules.append("value_domain")
    if missing_count or extra_count or source_row_count <= 0:
        failed_rules.append("source_key_coverage")
    if value_mismatch_count:
        failed_rules.append("source_value_consistency")
    coverage_samples = (
        _coverage_failure_samples(
            connection,
            source_identity_sql=source_identity_sql,
            target_identity_sql=target_identity_sql,
        )
        if missing_count or extra_count
        else ()
    )
    value_samples = (
        _value_failure_samples(
            connection,
            source_value_sql=source_value_sql,
            target_value_sql=target_value_sql,
            key_columns=key_columns,
        )
        if value_mismatch_count
        else ()
    )
    samples = tuple(
        (coverage_samples + value_samples)[:QFQ_NINETURN_FAILURE_SAMPLE_LIMIT]
    )
    return QfqNineturnIntegrityDiagnostics(
        passed=not failed_rules,
        checked_row_count=row_count,
        source_row_count=source_row_count,
        duplicate_key_count=duplicate_count,
        null_key_count=null_count,
        invalid_value_count=invalid_count + partition_count,
        missing_source_key_count=missing_count,
        extra_output_key_count=extra_count,
        source_value_mismatch_count=value_mismatch_count,
        failed_rule_names=tuple(failed_rules),
        failure_samples=samples,
    )


def _schema_tuple(schema: Sequence[ColumnContract]) -> tuple[tuple[str, str], ...]:
    return tuple((column.name, column.type.upper()) for column in schema)


def _read_parquet_paths(paths: Sequence[Path]) -> str:
    if len(paths) == 1:
        return read_parquet(paths[0], hive_partitioning=False)
    values = ", ".join(duckdb_string(path) for path in paths)
    return f"read_parquet([{values}], hive_partitioning=false, union_by_name=true)"


def _source_identity_sql(*, source: str, partition_key: str, freq: int | None) -> str:
    if freq is None:
        return f"""
        SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code,
          CAST(trade_date AS DATE) AS trade_date
        FROM {source}
        WHERE CAST(trade_date AS DATE) = DATE {duckdb_string(partition_key)}
        """
    return f"""
    SELECT DISTINCT CAST(ts_code AS VARCHAR) AS ts_code,
      CAST(freq AS INTEGER) AS freq,
      CAST(trade_time AS TIMESTAMP) AS trade_time
    FROM {source}
    WHERE CAST(freq AS INTEGER) = {freq}
      AND CAST(trade_date AS DATE) = DATE {duckdb_string(partition_key)}
    """


def _target_identity_sql(*, target: str, freq: int | None) -> str:
    columns = "ts_code, trade_date" if freq is None else "ts_code, freq, trade_time"
    return f"SELECT DISTINCT {columns} FROM {target}"


def _source_value_sql(*, source: str, partition_key: str, freq: int | None) -> str:
    if freq is None:
        return f"""
        SELECT CAST(ts_code AS VARCHAR) AS ts_code,
          CAST(trade_date AS DATE) AS trade_date,
          min(CAST(close AS DOUBLE)) AS source_close,
          count(*) AS source_key_count
        FROM {source}
        WHERE CAST(trade_date AS DATE) = DATE {duckdb_string(partition_key)}
        GROUP BY ts_code, trade_date
        """
    return f"""
    SELECT CAST(ts_code AS VARCHAR) AS ts_code,
      CAST(freq AS INTEGER) AS freq,
      CAST(trade_time AS TIMESTAMP) AS trade_time,
      min(CAST(close AS DOUBLE)) AS source_close,
      count(*) AS source_key_count
    FROM {source}
    WHERE CAST(freq AS INTEGER) = {freq}
      AND CAST(trade_date AS DATE) = DATE {duckdb_string(partition_key)}
    GROUP BY ts_code, freq, trade_time
    """


def _target_value_sql(*, target: str, freq: int | None) -> str:
    columns = "ts_code, trade_date" if freq is None else "ts_code, freq, trade_time"
    return f"SELECT {columns}, CAST(close_qfq AS DOUBLE) AS close_qfq FROM {target}"


def _coverage_failure_samples(
    connection: duckdb.DuckDBPyConnection,
    *,
    source_identity_sql: str,
    target_identity_sql: str,
) -> tuple[dict[str, object], ...]:
    rows = connection.execute(
        f"""
        WITH source_keys AS ({source_identity_sql}),
        target_keys AS ({target_identity_sql}),
        failures AS (
          SELECT 'missing_output' AS failure, * FROM (
            SELECT * FROM source_keys EXCEPT SELECT * FROM target_keys
          )
          UNION ALL BY NAME
          SELECT 'extra_output' AS failure, * FROM (
            SELECT * FROM target_keys EXCEPT SELECT * FROM source_keys
          )
        )
        SELECT * FROM failures
        ORDER BY failure, ts_code
        LIMIT {QFQ_NINETURN_FAILURE_SAMPLE_LIMIT}
        """
    ).fetchall()
    columns = [str(item[0]) for item in connection.description]
    return tuple(dict(zip(columns, row, strict=True)) for row in rows)


def _value_failure_samples(
    connection: duckdb.DuckDBPyConnection,
    *,
    source_value_sql: str,
    target_value_sql: str,
    key_columns: str,
) -> tuple[dict[str, object], ...]:
    rows = connection.execute(
        f"""
        WITH source_values AS ({source_value_sql}),
        target_values AS ({target_value_sql})
        SELECT 'source_value_mismatch' AS failure,
          {', '.join(f'source.{column.strip()}' for column in key_columns.split(','))},
          source.source_close,
          target.close_qfq,
          source.source_key_count
        FROM source_values source
        INNER JOIN target_values target USING ({key_columns})
        WHERE source.source_key_count != 1
           OR target.close_qfq IS NULL
           OR source.source_close IS NULL
           OR abs(target.close_qfq - source.source_close)
                > 1e-10 * greatest(1.0, abs(source.source_close))
        ORDER BY {', '.join(f'source.{column.strip()}' for column in key_columns.split(','))}
        LIMIT {QFQ_NINETURN_FAILURE_SAMPLE_LIMIT}
        """
    ).fetchall()
    columns = [str(item[0]) for item in connection.description]
    return tuple(dict(zip(columns, row, strict=True)) for row in rows)


def _failed_file_contract(sample: dict[str, object]) -> QfqNineturnIntegrityDiagnostics:
    return _failed_diagnostics("file_contract", sample)


def _failed_source_coverage(
    sample: dict[str, object],
) -> QfqNineturnIntegrityDiagnostics:
    return _failed_diagnostics("source_key_coverage", sample)


def _failed_diagnostics(
    rule_name: str,
    sample: dict[str, object],
) -> QfqNineturnIntegrityDiagnostics:
    return QfqNineturnIntegrityDiagnostics(
        passed=False,
        checked_row_count=0,
        source_row_count=0,
        duplicate_key_count=0,
        null_key_count=0,
        invalid_value_count=0,
        missing_source_key_count=0,
        extra_output_key_count=0,
        source_value_mismatch_count=0,
        failed_rule_names=(rule_name,),
        failure_samples=(sample,),
    )
