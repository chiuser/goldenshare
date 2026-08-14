"""Formula-free integrity audit for major-index nine-turn partitions."""

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
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_MAJOR_INDEX_DAILY_NINETURN_SCHEMA,
    GOLD_MAJOR_INDEX_MINS_NINETURN_SCHEMA,
)
from orchestrator.defs.run_contracts.major_index_nineturn import (
    MAJOR_INDEX_NINETURN_SIGNAL_THRESHOLD,
    normalize_major_index_nineturn_minute_freq,
)

MAJOR_INDEX_NINETURN_INTEGRITY_RULE_NAMES = (
    "file_contract",
    "partition_alignment",
    "key_integrity",
    "value_domain",
    "source_key_coverage",
    "source_value_consistency",
)


@dataclass(frozen=True, slots=True)
class MajorIndexNineturnIntegrityDiagnostics:
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

    @property
    def failed_row_count(self) -> int:
        return sum(
            (
                self.duplicate_key_count,
                self.null_key_count,
                self.invalid_value_count,
                self.missing_source_key_count,
                self.extra_output_key_count,
                self.source_value_mismatch_count,
            )
        )


def audit_major_index_nineturn_integrity(
    connection: duckdb.DuckDBPyConnection,
    *,
    target_path: Path,
    source_paths: Sequence[Path],
    partition_key: str,
    freq: int | None,
) -> MajorIndexNineturnIntegrityDiagnostics:
    normalized_freq = (
        None if freq is None else normalize_major_index_nineturn_minute_freq(freq)
    )
    if not target_path.is_file():
        return _failed("file_contract")
    existing_sources = tuple(path for path in source_paths if path.is_file())
    if not existing_sources:
        return _failed("source_key_coverage")
    schema = (
        GOLD_MAJOR_INDEX_DAILY_NINETURN_SCHEMA
        if normalized_freq is None
        else GOLD_MAJOR_INDEX_MINS_NINETURN_SCHEMA
    )
    try:
        observed_schema = tuple(
            (str(row[0]), str(row[1]).upper())
            for row in connection.execute(
                describe_parquet_query(target_path, hive_partitioning=False)
            ).fetchall()
        )
    except Exception:  # noqa: BLE001 - unreadable parquet is a failed check.
        return _failed("file_contract")
    expected_schema = tuple((column.name, column.type.upper()) for column in schema)
    if observed_schema != expected_schema:
        return _failed("file_contract")

    target = read_parquet(target_path, hive_partitioning=False)
    source = _read_paths(existing_sources)
    key_columns = (
        "ts_code, trade_date"
        if normalized_freq is None
        else "ts_code, freq, trade_time"
    )
    minute_nulls = (
        "" if normalized_freq is None else "OR freq IS NULL OR trade_time IS NULL"
    )
    minute_partition = (
        ""
        if normalized_freq is None
        else f"OR freq != {normalized_freq} OR CAST(trade_time AS DATE) != trade_date"
    )
    metrics = connection.execute(
        f"""
        SELECT
          count(*),
          count(*) - count(DISTINCT ({key_columns})),
          count(*) FILTER (
            WHERE ts_code IS NULL OR trim(ts_code) = '' OR trade_date IS NULL
              {minute_nulls}
          ),
          count(*) FILTER (
            WHERE trade_date != DATE {duckdb_string(partition_key)}
              {minute_partition}
          ),
          count(*) FILTER (
            WHERE close IS NULL OR NOT isfinite(close) OR close <= 0
              OR up_count IS NULL OR down_count IS NULL
              OR up_count < 0 OR down_count < 0
              OR (up_count > 0 AND down_count > 0)
              OR (nine_up_turn IS NOT NULL AND nine_up_turn != '+9')
              OR (nine_down_turn IS NOT NULL AND nine_down_turn != '-9')
              OR (nine_up_turn = '+9' AND up_count < {MAJOR_INDEX_NINETURN_SIGNAL_THRESHOLD})
              OR (nine_down_turn = '-9' AND down_count < {MAJOR_INDEX_NINETURN_SIGNAL_THRESHOLD})
              OR (nine_up_turn IS NOT NULL AND nine_down_turn IS NOT NULL)
          )
        FROM {target}
        """
    ).fetchone()
    row_count, duplicate_count, null_count, partition_count, invalid_count = (
        int(value or 0) for value in metrics
    )
    source_values = _source_values_sql(
        source=source,
        partition_key=partition_key,
        freq=normalized_freq,
    )
    target_values = _target_values_sql(target=target, freq=normalized_freq)
    source_row_count, missing_count, extra_count, mismatch_count = (
        int(value or 0)
        for value in connection.execute(
            f"""
            WITH source_values AS ({source_values}),
            target_values AS ({target_values})
            SELECT
              (SELECT count(*) FROM source_values),
              (SELECT count(*) FROM (
                SELECT {key_columns} FROM source_values
                EXCEPT SELECT {key_columns} FROM target_values
              )),
              (SELECT count(*) FROM (
                SELECT {key_columns} FROM target_values
                EXCEPT SELECT {key_columns} FROM source_values
              )),
              (SELECT count(*) FROM source_values source
               INNER JOIN target_values target USING ({key_columns})
               WHERE source.source_key_count != 1
                  OR target.close IS NULL
                  OR abs(target.close - source.source_close)
                       > 1e-10 * greatest(1.0, abs(source.source_close)))
            """
        ).fetchone()
    )
    failed: list[str] = []
    if row_count <= 0:
        failed.append("file_contract")
    if partition_count:
        failed.append("partition_alignment")
    if duplicate_count or null_count:
        failed.append("key_integrity")
    if invalid_count:
        failed.append("value_domain")
    if source_row_count <= 0 or missing_count or extra_count:
        failed.append("source_key_coverage")
    if mismatch_count:
        failed.append("source_value_consistency")
    return MajorIndexNineturnIntegrityDiagnostics(
        passed=not failed,
        checked_row_count=row_count,
        source_row_count=source_row_count,
        duplicate_key_count=duplicate_count,
        null_key_count=null_count,
        invalid_value_count=invalid_count + partition_count,
        missing_source_key_count=missing_count,
        extra_output_key_count=extra_count,
        source_value_mismatch_count=mismatch_count,
        failed_rule_names=tuple(failed),
    )


def _failed(rule: str) -> MajorIndexNineturnIntegrityDiagnostics:
    return MajorIndexNineturnIntegrityDiagnostics(
        passed=False,
        checked_row_count=0,
        source_row_count=0,
        duplicate_key_count=0,
        null_key_count=0,
        invalid_value_count=0,
        missing_source_key_count=0,
        extra_output_key_count=0,
        source_value_mismatch_count=0,
        failed_rule_names=(rule,),
    )


def _source_values_sql(*, source: str, partition_key: str, freq: int | None) -> str:
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
    WHERE CAST(trade_date AS DATE) = DATE {duckdb_string(partition_key)}
      AND CAST(freq AS INTEGER) = {freq}
    GROUP BY ts_code, freq, trade_time
    """


def _target_values_sql(*, target: str, freq: int | None) -> str:
    columns = "ts_code, trade_date" if freq is None else "ts_code, freq, trade_time"
    return f"SELECT {columns}, CAST(close AS DOUBLE) AS close FROM {target}"


def _read_paths(paths: Sequence[Path]) -> str:
    if len(paths) == 1:
        return read_parquet(paths[0], hive_partitioning=False)
    values = ", ".join(duckdb_string(path) for path in paths)
    return f"read_parquet([{values}], hive_partitioning=false, union_by_name=true)"


__all__ = [
    "MAJOR_INDEX_NINETURN_INTEGRITY_RULE_NAMES",
    "MajorIndexNineturnIntegrityDiagnostics",
    "audit_major_index_nineturn_integrity",
]
