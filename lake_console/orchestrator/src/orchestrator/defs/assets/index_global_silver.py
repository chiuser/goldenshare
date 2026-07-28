"""DuckDB Silver writer and Dagster asset for international indexes."""

from dataclasses import dataclass
import os
from pathlib import Path
from time import perf_counter
from typing import Any

import dagster as dg

from orchestrator.defs.assets.index_global_raw import raw_index_global
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_index_global_path,
    silver_index_global_path,
    silver_index_global_staging_path,
)
from orchestrator.defs.partitions import cn_global_index_trade_days
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_GLOBAL_SCHEMA,
    SILVER_INDEX_GLOBAL_SCHEMA,
)
from orchestrator.defs.run_contracts.index_global import (
    INDEX_GLOBAL_EXPECTED_CODES,
    IndexGlobalSilverConfig,
    SILVER_INDEX_GLOBAL_FIELDS,
    normalize_index_global_trade_date,
    validate_index_global_silver_config,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)


class IndexGlobalSilverValidationError(ValueError):
    """Raised when a Raw partition cannot be promoted to Silver."""


@dataclass(frozen=True, slots=True)
class IndexGlobalSilverWriteResult:
    partition_key: str
    source_file_path: Path
    target_file_path: Path
    staging_path: Path
    source_row_count: int
    output_row_count: int
    duplicate_removed_count: int
    rejected_row_count: int
    reject_reason_counts: dict[str, int]
    observed_columns: tuple[str, ...]
    elapsed_ms: float
    promoted: bool

    def to_details(self) -> dict[str, object]:
        return {
            "partition_key": self.partition_key,
            "source_file_path": str(self.source_file_path),
            "target_file_path": str(self.target_file_path),
            "source_row_count": self.source_row_count,
            "output_row_count": self.output_row_count,
            "duplicate_removed_count": self.duplicate_removed_count,
            "rejected_row_count": self.rejected_row_count,
            "reject_reason_counts": dict(self.reject_reason_counts),
            "output_columns": list(self.observed_columns),
            "elapsed_ms": round(self.elapsed_ms, 3),
            "promoted": self.promoted,
        }


def _column_contracts(schema: tuple[object, ...]) -> tuple[tuple[str, str], ...]:
    return tuple((str(column.name), str(column.type).upper()) for column in schema)


def _describe_columns(connection: Any, path: Path) -> tuple[tuple[str, str], ...]:
    return tuple(
        (str(row[0]), str(row[1]).upper())
        for row in connection.execute(describe_parquet_query(path)).fetchall()
    )


def _assert_schema(
    connection: Any,
    path: Path,
    schema: tuple[object, ...],
    *,
    label: str,
) -> None:
    expected = _column_contracts(schema)
    observed = _describe_columns(connection, path)
    if observed != expected:
        raise IndexGlobalSilverValidationError(
            f"{label} schema does not match contract: "
            f"expected={expected!r}, observed={observed!r}"
        )


def _normalized_sql(raw_path: Path) -> str:
    source = read_parquet(raw_path, hive_partitioning=False)
    return f"""
SELECT
  upper(trim(CAST(ts_code AS VARCHAR))) AS ts_code,
  CAST(try_strptime(NULLIF(trim(CAST(trade_date AS VARCHAR)), ''), '%Y%m%d') AS DATE) AS trade_date,
  CAST(open AS DOUBLE) AS open,
  CAST(high AS DOUBLE) AS high,
  CAST(low AS DOUBLE) AS low,
  CAST(close AS DOUBLE) AS close,
  CAST(pre_close AS DOUBLE) AS pre_close,
  CAST(change AS DOUBLE) AS change_amount,
  CAST(pct_chg AS DOUBLE) AS pct_chg,
  CAST(swing AS DOUBLE) AS swing,
  CAST(vol AS DOUBLE) AS vol,
  CAST(amount AS DOUBLE) AS amount
FROM {source}
"""


def _expected_codes_sql() -> str:
    return ", ".join(duckdb_string(code) for code in INDEX_GLOBAL_EXPECTED_CODES)


def _rejection_counts(
    connection: Any,
    normalized_sql: str,
    *,
    partition_key: str,
) -> dict[str, int]:
    expected_codes = _expected_codes_sql()
    rows = connection.execute(
        f"""
        WITH normalized AS ({normalized_sql})
        SELECT reason_code, count(*) AS row_count
        FROM (
          SELECT CASE
            WHEN ts_code IS NULL OR trim(ts_code) = '' THEN 'ts_code_missing'
            WHEN ts_code NOT IN ({expected_codes}) THEN 'ts_code_unknown'
            WHEN trade_date IS NULL THEN 'trade_date_invalid'
            WHEN trade_date <> CAST({duckdb_string(partition_key)} AS DATE)
              THEN 'trade_date_out_of_partition'
            WHEN (open IS NOT NULL AND NOT isfinite(open))
              OR (high IS NOT NULL AND NOT isfinite(high))
              OR (low IS NOT NULL AND NOT isfinite(low))
              OR (close IS NOT NULL AND NOT isfinite(close))
              OR (pre_close IS NOT NULL AND NOT isfinite(pre_close))
              OR (change_amount IS NOT NULL AND NOT isfinite(change_amount))
              OR (pct_chg IS NOT NULL AND NOT isfinite(pct_chg))
              OR (swing IS NOT NULL AND NOT isfinite(swing))
              OR (vol IS NOT NULL AND NOT isfinite(vol))
              OR (amount IS NOT NULL AND NOT isfinite(amount))
              THEN 'numeric_not_finite'
            ELSE NULL
          END AS reason_code
          FROM normalized
        ) rejected
        WHERE reason_code IS NOT NULL
        GROUP BY reason_code
        ORDER BY reason_code
        """
    ).fetchall()
    return {str(reason): int(count) for reason, count in rows}


def _duplicate_counts(
    connection: Any,
    normalized_sql: str,
) -> tuple[int, int]:
    value_columns = tuple(
        field for field in SILVER_INDEX_GLOBAL_FIELDS if field not in {"ts_code", "trade_date"}
    )
    values_sql = ", ".join(f'"{field}"' for field in value_columns)
    duplicates, conflicts = connection.execute(
        f"""
        WITH normalized AS ({normalized_sql}), grouped AS (
          SELECT ts_code, trade_date, count(*) AS row_count,
                 count(DISTINCT ({values_sql})) AS value_versions
          FROM normalized
          GROUP BY ts_code, trade_date
        )
        SELECT
          coalesce(sum(CASE WHEN row_count > 1 THEN row_count - 1 ELSE 0 END), 0),
          coalesce(sum(CASE WHEN row_count > 1 AND value_versions > 1 THEN 1 ELSE 0 END), 0)
        FROM grouped
        """
    ).fetchone()
    return int(duplicates or 0), int(conflicts or 0)


def _output_sql(normalized_sql: str) -> str:
    return (
        f"SELECT DISTINCT * FROM ({normalized_sql}) normalized "
        "ORDER BY ts_code, trade_date"
    )


def _validate_staging(
    connection: Any,
    staging_path: Path,
    *,
    partition_key: str,
    expected_row_count: int,
) -> int:
    _assert_schema(
        connection,
        staging_path,
        SILVER_INDEX_GLOBAL_SCHEMA,
        label="silver index_global staging",
    )
    actual_row_count, invalid_scope, duplicate_count, non_finite = connection.execute(
        f"""
        SELECT
          count(*),
          count(*) FILTER (
            WHERE ts_code IS NULL
               OR ts_code NOT IN ({_expected_codes_sql()})
               OR trade_date IS NULL
               OR trade_date <> CAST({duckdb_string(partition_key)} AS DATE)
          ),
          count(*) - count(DISTINCT (ts_code, trade_date)),
          count(*) FILTER (
            WHERE (open IS NOT NULL AND NOT isfinite(open))
               OR (high IS NOT NULL AND NOT isfinite(high))
               OR (low IS NOT NULL AND NOT isfinite(low))
               OR (close IS NOT NULL AND NOT isfinite(close))
               OR (pre_close IS NOT NULL AND NOT isfinite(pre_close))
               OR (change_amount IS NOT NULL AND NOT isfinite(change_amount))
               OR (pct_chg IS NOT NULL AND NOT isfinite(pct_chg))
               OR (swing IS NOT NULL AND NOT isfinite(swing))
               OR (vol IS NOT NULL AND NOT isfinite(vol))
               OR (amount IS NOT NULL AND NOT isfinite(amount))
          )
        FROM {read_parquet(staging_path, hive_partitioning=False)}
        """
    ).fetchone()
    if int(invalid_scope) or int(duplicate_count) or int(non_finite):
        raise IndexGlobalSilverValidationError(
            "silver index_global staging validation failed: "
            f"invalid_scope={invalid_scope}, duplicate_count={duplicate_count}, "
            f"non_finite={non_finite}"
        )
    if int(actual_row_count) != expected_row_count:
        raise IndexGlobalSilverValidationError(
            "silver index_global staging row count changed: "
            f"expected={expected_row_count}, actual={actual_row_count}"
        )
    return int(actual_row_count)


def write_silver_index_global_partition(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    partition_key: str,
    run_id: str,
) -> IndexGlobalSilverWriteResult:
    """Normalize one Raw date partition into Silver using one DuckDB query."""

    normalized_partition_key = normalize_index_global_trade_date(partition_key)
    raw_path = raw_index_global_path(lake_root_path, normalized_partition_key)
    target_path = silver_index_global_path(lake_root_path, normalized_partition_key)
    staging_path = silver_index_global_staging_path(
        lake_root_path,
        run_id,
        normalized_partition_key,
    )
    if not raw_path.exists():
        raise FileNotFoundError(f"Missing index_global Raw file: {raw_path}")
    if staging_path.exists():
        staging_path.unlink()

    started_at = perf_counter()
    promoted = False
    try:
        with duckdb_resource.connect() as connection:
            _assert_schema(
                connection,
                raw_path,
                RAW_INDEX_GLOBAL_SCHEMA,
                label="index_global Raw",
            )
            normalized_sql = _normalized_sql(raw_path)
            source_row_count = int(
                connection.execute(
                    f"SELECT count(*) FROM ({normalized_sql}) normalized"
                ).fetchone()[0]
            )
            reject_reason_counts = _rejection_counts(
                connection,
                normalized_sql,
                partition_key=normalized_partition_key,
            )
            rejected_row_count = sum(reject_reason_counts.values())
            if rejected_row_count:
                raise IndexGlobalSilverValidationError(
                    "index_global Silver normalization rejected rows: "
                    f"{reject_reason_counts}"
                )

            duplicate_removed_count, conflict_key_count = _duplicate_counts(
                connection,
                normalized_sql,
            )
            if conflict_key_count:
                raise IndexGlobalSilverValidationError(
                    "index_global Silver has conflicting duplicate business keys: "
                    f"conflict_key_count={conflict_key_count}"
                )

            output_sql = _output_sql(normalized_sql)
            expected_output_count = int(
                connection.execute(
                    f"SELECT count(*) FROM ({output_sql}) output_rows"
                ).fetchone()[0]
            )
            staging_path.parent.mkdir(parents=True, exist_ok=True)
            connection.execute(copy_query_to_parquet(output_sql, staging_path))
            output_row_count = _validate_staging(
                connection,
                staging_path,
                partition_key=normalized_partition_key,
                expected_row_count=expected_output_count,
            )

        target_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging_path, target_path)
        promoted = True
        return IndexGlobalSilverWriteResult(
            partition_key=normalized_partition_key,
            source_file_path=raw_path,
            target_file_path=target_path,
            staging_path=staging_path,
            source_row_count=source_row_count,
            output_row_count=output_row_count,
            duplicate_removed_count=duplicate_removed_count,
            rejected_row_count=rejected_row_count,
            reject_reason_counts=reject_reason_counts,
            observed_columns=SILVER_INDEX_GLOBAL_FIELDS,
            elapsed_ms=(perf_counter() - started_at) * 1000,
            promoted=True,
        )
    finally:
        if not promoted and staging_path.exists():
            staging_path.unlink()


@dg.asset(
    name="silver_index_global",
    partitions_def=cn_global_index_trade_days,
    deps=[raw_index_global],
    group_name="index",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id="index_global",
        source_system=SourceSystem.DERIVED,
        data_contract="silver_index_global_by_trade_date",
        column_schema=SILVER_INDEX_GLOBAL_SCHEMA,
        path_template=lake_path_template(
            silver_index_global_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        extra_metadata={
            "partition_set": cn_global_index_trade_days.name,
            "write_boundary": "p5_dagster_asset",
            "empty_natural_day_allowed": True,
        },
    ),
    description="国际指数日线 Silver，按同日 Raw 做 DuckDB set-based 标准化。",
)
def silver_index_global(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    config: IndexGlobalSilverConfig,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = validate_index_global_silver_config(
        config,
        partition_key=context.partition_key,
    )
    result = write_silver_index_global_partition(
        lake_root_path=lake_root.root(),
        duckdb_resource=duckdb,
        partition_key=partition_key,
        run_id=context.run_id,
    )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=result.target_file_path,
            row_count=result.output_row_count,
            observed_columns=result.observed_columns,
            extra_metadata={
                "partition_key": result.partition_key,
                "attempt": config.attempt,
                "source_file_path": str(result.source_file_path),
                "source_row_count": result.source_row_count,
                "duplicate_removed_count": result.duplicate_removed_count,
                "rejected_row_count": result.rejected_row_count,
                "reject_reason_counts": result.reject_reason_counts,
                "elapsed_ms": round(result.elapsed_ms, 3),
            },
        )
    )
