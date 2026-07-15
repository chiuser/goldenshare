"""Silver writers and assets for the Eastmoney board datasets.

M5 keeps the transformation set-based and partition-local.  Raw files remain
the only source input; cross-dataset membership differences are intentionally
not treated as Silver failures.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import os
from time import perf_counter
from uuid import uuid4

import dagster as dg

from orchestrator.defs.assets.dc_board_raw import (
    raw_tushare_dc_daily,
    raw_tushare_dc_index,
    raw_tushare_dc_member,
)
from orchestrator.defs.duckdb_sql import (
    copy_query_to_parquet,
    describe_parquet_query,
    duckdb_string,
    read_parquet,
)
from orchestrator.defs.partitions import cn_a_index_trade_days
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_dc_daily_path,
    raw_dc_index_path,
    raw_dc_member_path,
    silver_dc_daily_path,
    silver_dc_index_path,
    silver_dc_member_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_DC_DAILY_SCHEMA,
    RAW_TUSHARE_DC_INDEX_SCHEMA,
    RAW_TUSHARE_DC_MEMBER_SCHEMA,
    SILVER_DC_DAILY_SCHEMA,
    SILVER_DC_INDEX_SCHEMA,
    SILVER_DC_MEMBER_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.dc_board import (
    DC_DAILY_CATEGORIES,
    DC_INDEX_TYPES,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)


_BOARD_CODE_RE = r"^BK[0-9]{4}\.DC$"
_STOCK_CODE_RE = r"^[0-9]{6}\.(SZ|SH|BJ)$"


class DcBoardSilverValidationError(ValueError):
    """Raised when a Raw partition cannot produce a valid Silver partition."""


@dataclass(frozen=True, slots=True)
class DcBoardSilverWriteResult:
    dataset: str
    partition_key: str
    source_file_path: Path
    target_file_path: Path
    source_row_count: int
    output_row_count: int
    duplicate_removed_count: int
    conflict_key_count: int
    rejected_row_count: int
    reject_reason_counts: dict[str, int]
    observed_columns: tuple[str, ...]
    elapsed_ms: float

    def to_metadata(self) -> dict[str, object]:
        return {
            "dataset": self.dataset,
            "partition_key": self.partition_key,
            "source_asset": f"raw_tushare_{self.dataset}",
            "source_file_path": str(self.source_file_path),
            "target_file_path": str(self.target_file_path),
            "source_row_count": self.source_row_count,
            "output_row_count": self.output_row_count,
            "duplicate_removed_count": self.duplicate_removed_count,
            "conflict_key_count": self.conflict_key_count,
            "rejected_row_count": self.rejected_row_count,
            "reject_reason_counts": self.reject_reason_counts,
            "observed_columns": list(self.observed_columns),
            "elapsed_ms": round(self.elapsed_ms, 3),
            "write_mode": "duckdb_set_based_atomic_replace",
        }


@dataclass(frozen=True, slots=True)
class DcBoardSilverStagingResult:
    """Validated Silver output that has not been promoted yet."""

    result: DcBoardSilverWriteResult
    staging_path: Path


@dataclass(frozen=True, slots=True)
class _SilverSpec:
    dataset: str
    raw_schema: Sequence[object]
    silver_schema: Sequence[object]
    key_columns: tuple[str, ...]
    raw_path_builder: object
    silver_path_builder: object
    normalized_sql_builder: object
    rejection_sql_builder: object


def _normalized_trade_date_sql(column: str = "trade_date") -> str:
    return (
        "CAST(try_strptime(replace(trim(CAST(" + column + " AS VARCHAR)), '-', ''), '%Y%m%d') AS DATE)"
    )


def _dc_index_normalized_sql(raw_path: Path) -> str:
    return f"""
        SELECT
            upper(trim(CAST(ts_code AS VARCHAR))) AS ts_code,
            {_normalized_trade_date_sql()} AS trade_date,
            trim(CAST(name AS VARCHAR)) AS name,
            NULLIF(trim(CAST("leading" AS VARCHAR)), '') AS "leading",
            NULLIF(upper(trim(CAST(leading_code AS VARCHAR))), '') AS leading_code,
            CAST(pct_change AS DOUBLE) AS pct_change,
            CAST(leading_pct AS DOUBLE) AS leading_pct,
            CAST(total_mv AS DOUBLE) AS total_mv,
            CAST(turnover_rate AS DOUBLE) AS turnover_rate,
            CAST(up_num AS INTEGER) AS up_num,
            CAST(down_num AS INTEGER) AS down_num,
            trim(CAST(idx_type AS VARCHAR)) AS idx_type,
            NULLIF(trim(CAST(level AS VARCHAR)), '') AS level
        FROM {read_parquet(raw_path, hive_partitioning=False)}
    """


def _dc_member_normalized_sql(raw_path: Path) -> str:
    return f"""
        SELECT
            {_normalized_trade_date_sql()} AS trade_date,
            upper(trim(CAST(ts_code AS VARCHAR))) AS ts_code,
            upper(trim(CAST(con_code AS VARCHAR))) AS con_code,
            trim(CAST(name AS VARCHAR)) AS name
        FROM {read_parquet(raw_path, hive_partitioning=False)}
    """


def _dc_daily_normalized_sql(raw_path: Path) -> str:
    return f"""
        SELECT
            upper(trim(CAST(ts_code AS VARCHAR))) AS ts_code,
            {_normalized_trade_date_sql()} AS trade_date,
            CAST(close AS DOUBLE) AS close,
            CAST(open AS DOUBLE) AS open,
            CAST(high AS DOUBLE) AS high,
            CAST(low AS DOUBLE) AS low,
            CAST(change AS DOUBLE) AS change,
            CAST(pct_change AS DOUBLE) AS pct_change,
            CAST(vol AS DOUBLE) AS vol,
            CAST(amount AS DOUBLE) AS amount,
            CAST(swing AS DOUBLE) AS swing,
            CAST(turnover_rate AS DOUBLE) AS turnover_rate,
            trim(CAST(category AS VARCHAR)) AS category
        FROM {read_parquet(raw_path, hive_partitioning=False)}
    """


def _dc_index_rejection_sql(normalized_sql: str, partition_key: str) -> str:
    return f"""
        WITH normalized AS ({normalized_sql}), rejected AS (
            SELECT CASE
                WHEN trade_date IS NULL THEN 'invalid_trade_date'
                WHEN trade_date <> CAST({duckdb_string(partition_key)} AS DATE) THEN 'trade_date_out_of_partition'
                WHEN ts_code IS NULL OR NOT regexp_full_match(ts_code, '{_BOARD_CODE_RE}') THEN 'invalid_board_code'
                WHEN name IS NULL OR trim(name) = '' THEN 'blank_board_name'
                WHEN leading_code IS NOT NULL AND NOT regexp_full_match(leading_code, '{_STOCK_CODE_RE}') THEN 'invalid_leading_code'
                WHEN idx_type IS NULL OR idx_type NOT IN ({', '.join(duckdb_string(value) for value in DC_INDEX_TYPES)}) THEN 'invalid_idx_type'
                WHEN (pct_change IS NOT NULL AND NOT isfinite(pct_change))
                  OR (leading_pct IS NOT NULL AND NOT isfinite(leading_pct))
                  OR (total_mv IS NOT NULL AND (NOT isfinite(total_mv) OR total_mv < 0))
                  OR (turnover_rate IS NOT NULL AND (NOT isfinite(turnover_rate) OR turnover_rate < 0))
                  OR (up_num IS NOT NULL AND up_num < 0)
                  OR (down_num IS NOT NULL AND down_num < 0)
                    THEN 'invalid_numeric_domain'
                ELSE NULL
            END AS reason
            FROM normalized
        )
        SELECT reason, count(*) AS rejected_row_count
        FROM rejected
        WHERE reason IS NOT NULL
        GROUP BY reason
        ORDER BY reason
    """


def _dc_member_rejection_sql(normalized_sql: str, partition_key: str) -> str:
    return f"""
        WITH normalized AS ({normalized_sql}), rejected AS (
            SELECT CASE
                WHEN trade_date IS NULL THEN 'invalid_trade_date'
                WHEN trade_date <> CAST({duckdb_string(partition_key)} AS DATE) THEN 'trade_date_out_of_partition'
                WHEN ts_code IS NULL OR NOT regexp_full_match(ts_code, '{_BOARD_CODE_RE}') THEN 'invalid_board_code'
                WHEN con_code IS NULL OR NOT regexp_full_match(con_code, '{_STOCK_CODE_RE}') THEN 'invalid_stock_code'
                WHEN name IS NULL OR trim(name) = '' THEN 'blank_member_name'
                ELSE NULL
            END AS reason
            FROM normalized
        )
        SELECT reason, count(*) AS rejected_row_count
        FROM rejected
        WHERE reason IS NOT NULL
        GROUP BY reason
        ORDER BY reason
    """


def _dc_daily_rejection_sql(normalized_sql: str, partition_key: str) -> str:
    allowed_categories = ", ".join(duckdb_string(value) for value in DC_DAILY_CATEGORIES)
    return f"""
        WITH normalized AS ({normalized_sql}), rejected AS (
            SELECT CASE
                WHEN trade_date IS NULL THEN 'invalid_trade_date'
                WHEN trade_date <> CAST({duckdb_string(partition_key)} AS DATE) THEN 'trade_date_out_of_partition'
                WHEN ts_code IS NULL OR NOT regexp_full_match(ts_code, '{_BOARD_CODE_RE}') THEN 'invalid_board_code'
                WHEN category IS NULL OR category NOT IN ({allowed_categories}) THEN 'invalid_category'
                WHEN (close IS NOT NULL AND (NOT isfinite(close) OR close < 0))
                  OR (open IS NOT NULL AND (NOT isfinite(open) OR open < 0))
                  OR (high IS NOT NULL AND (NOT isfinite(high) OR high < 0))
                  OR (low IS NOT NULL AND (NOT isfinite(low) OR low < 0))
                  OR (vol IS NOT NULL AND (NOT isfinite(vol) OR vol < 0))
                  OR (amount IS NOT NULL AND (NOT isfinite(amount) OR amount < 0))
                  OR (swing IS NOT NULL AND (NOT isfinite(swing) OR swing < 0))
                  OR (turnover_rate IS NOT NULL AND (NOT isfinite(turnover_rate) OR turnover_rate < 0))
                  OR (change IS NOT NULL AND NOT isfinite(change))
                  OR (pct_change IS NOT NULL AND NOT isfinite(pct_change))
                    THEN 'invalid_numeric_domain'
                ELSE NULL
            END AS reason
            FROM normalized
        )
        SELECT reason, count(*) AS rejected_row_count
        FROM rejected
        WHERE reason IS NOT NULL
        GROUP BY reason
        ORDER BY reason
    """


_SPECS = {
    "dc_index": _SilverSpec(
        dataset="dc_index",
        raw_schema=RAW_TUSHARE_DC_INDEX_SCHEMA,
        silver_schema=SILVER_DC_INDEX_SCHEMA,
        key_columns=("ts_code", "trade_date"),
        raw_path_builder=raw_dc_index_path,
        silver_path_builder=silver_dc_index_path,
        normalized_sql_builder=_dc_index_normalized_sql,
        rejection_sql_builder=_dc_index_rejection_sql,
    ),
    "dc_member": _SilverSpec(
        dataset="dc_member",
        raw_schema=RAW_TUSHARE_DC_MEMBER_SCHEMA,
        silver_schema=SILVER_DC_MEMBER_SCHEMA,
        key_columns=("trade_date", "ts_code", "con_code"),
        raw_path_builder=raw_dc_member_path,
        silver_path_builder=silver_dc_member_path,
        normalized_sql_builder=_dc_member_normalized_sql,
        rejection_sql_builder=_dc_member_rejection_sql,
    ),
    "dc_daily": _SilverSpec(
        dataset="dc_daily",
        raw_schema=RAW_TUSHARE_DC_DAILY_SCHEMA,
        silver_schema=SILVER_DC_DAILY_SCHEMA,
        key_columns=("ts_code", "trade_date", "category"),
        raw_path_builder=raw_dc_daily_path,
        silver_path_builder=silver_dc_daily_path,
        normalized_sql_builder=_dc_daily_normalized_sql,
        rejection_sql_builder=_dc_daily_rejection_sql,
    ),
}


def _column_contracts(schema: Sequence[object]) -> tuple[tuple[str, str], ...]:
    return tuple((str(column.name), str(column.type).upper()) for column in schema)


def _schema_mismatches(connection, path: Path, schema: Sequence[object]) -> dict[str, object]:
    expected = _column_contracts(schema)
    observed = tuple(
        (str(row[0]), str(row[1]).upper())
        for row in connection.execute(describe_parquet_query(path)).fetchall()
    )
    return {
        "expected_columns": [name for name, _ in expected],
        "observed_columns": [name for name, _ in observed],
        "expected_types": {name: type_name for name, type_name in expected},
        "observed_types": {name: type_name for name, type_name in observed},
        "mismatch": observed != expected,
    }


def _open_day_count(connection, calendar_path: Path, partition_key: str) -> int:
    return int(
        connection.execute(
            f"""
            SELECT count(*)
            FROM {read_parquet(calendar_path, hive_partitioning=False)}
            WHERE exchange = 'SSE'
              AND is_open = true
              AND trade_date = CAST({duckdb_string(partition_key)} AS DATE)
            """
        ).fetchone()[0]
    )


def _conflict_counts(connection, normalized_sql: str, key_columns: Sequence[str], value_columns: Sequence[str]) -> tuple[int, int]:
    key_expr = ", ".join(f'"{column}"' for column in key_columns)
    value_expr = ", ".join(f'"{column}"' for column in value_columns)
    duplicate_count, conflict_count = connection.execute(
        f"""
        WITH normalized AS ({normalized_sql}), grouped AS (
            SELECT {key_expr}, count(*) AS row_count,
                   count(DISTINCT ({value_expr})) AS value_versions
            FROM normalized
            GROUP BY {key_expr}
        )
        SELECT
            coalesce(sum(CASE WHEN row_count > 1 THEN row_count - 1 ELSE 0 END), 0),
            coalesce(sum(CASE WHEN row_count > 1 AND value_versions > 1 THEN 1 ELSE 0 END), 0)
        FROM grouped
        """
    ).fetchone()
    return int(duplicate_count or 0), int(conflict_count or 0)


def _stage_silver_partition(
    *,
    dataset: str,
    lake_root_path: Path,
    connection,
    partition_key: str,
    staging_tag: str,
) -> DcBoardSilverStagingResult:
    spec = _SPECS[dataset]
    raw_path = spec.raw_path_builder(lake_root_path, partition_key)
    target_path = spec.silver_path_builder(lake_root_path, partition_key)
    calendar_path = silver_trade_calendar_path(lake_root_path)
    started_at = perf_counter()

    if not raw_path.exists():
        raise FileNotFoundError(f"Missing raw {dataset} file: {raw_path}")
    if not calendar_path.exists():
        raise FileNotFoundError(f"Missing silver trade calendar file: {calendar_path}")

    if _open_day_count(connection, calendar_path, partition_key) != 1:
        raise DcBoardSilverValidationError(
            f"{dataset} partition {partition_key} is not exactly one SSE open day."
        )
    source_schema = _schema_mismatches(connection, raw_path, spec.raw_schema)
    if source_schema["mismatch"]:
        raise DcBoardSilverValidationError(
            f"raw {dataset} schema does not match contract: {source_schema}"
        )

    normalized_sql = spec.normalized_sql_builder(raw_path)
    source_row_count = int(
        connection.execute(f"SELECT count(*) FROM ({normalized_sql}) normalized").fetchone()[0]
    )
    if source_row_count <= 0:
        raise DcBoardSilverValidationError(
            f"raw {dataset} has no rows for {partition_key}."
        )

    rejection_rows = connection.execute(
        spec.rejection_sql_builder(normalized_sql, partition_key)
    ).fetchall()
    reject_reason_counts = {str(row[0]): int(row[1]) for row in rejection_rows}
    rejected_row_count = sum(reject_reason_counts.values())
    if rejected_row_count:
        raise DcBoardSilverValidationError(
            f"{dataset} Silver normalization rejected rows for {partition_key}: "
            f"{reject_reason_counts}"
        )

    value_columns = tuple(
        column.name for column in spec.silver_schema if column.name not in spec.key_columns
    )
    duplicate_removed_count, conflict_key_count = _conflict_counts(
        connection,
        normalized_sql,
        spec.key_columns,
        value_columns,
    )
    if conflict_key_count:
        raise DcBoardSilverValidationError(
            f"{dataset} has conflicting duplicate business keys for {partition_key}: "
            f"conflict_key_count={conflict_key_count}"
        )

    output_sql = (
        f"SELECT DISTINCT * FROM ({normalized_sql}) normalized "
        f"ORDER BY {', '.join(spec.key_columns)}"
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path = target_path.with_name(
        f"{target_path.name}.{staging_tag}-{uuid4().hex}.tmp"
    )
    try:
        connection.execute(copy_query_to_parquet(output_sql, staging_path))
        target_schema = _schema_mismatches(connection, staging_path, spec.silver_schema)
        if target_schema["mismatch"]:
            raise DcBoardSilverValidationError(
                f"silver {dataset} staging schema does not match contract: {target_schema}"
            )
        output_row_count = int(
            connection.execute(f"SELECT count(*) FROM {read_parquet(staging_path)}").fetchone()[0]
        )
        if output_row_count <= 0:
            raise DcBoardSilverValidationError(
                f"silver {dataset} staging has no rows for {partition_key}."
            )
    except Exception:
        if staging_path.exists():
            staging_path.unlink()
        raise

    return DcBoardSilverStagingResult(
        result=DcBoardSilverWriteResult(
            dataset=dataset,
            partition_key=partition_key,
            source_file_path=raw_path,
            target_file_path=target_path,
            source_row_count=source_row_count,
            output_row_count=output_row_count,
            duplicate_removed_count=duplicate_removed_count,
            conflict_key_count=conflict_key_count,
            rejected_row_count=rejected_row_count,
            reject_reason_counts=reject_reason_counts,
            observed_columns=tuple(column.name for column in spec.silver_schema),
            elapsed_ms=(perf_counter() - started_at) * 1000,
        ),
        staging_path=staging_path,
    )


def _write_silver_partition(
    *,
    dataset: str,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    partition_key: str,
) -> DcBoardSilverWriteResult:
    with duckdb_resource.connect() as connection:
        staged = _stage_silver_partition(
            dataset=dataset,
            lake_root_path=lake_root_path,
            connection=connection,
            partition_key=partition_key,
            staging_tag="m5",
        )
        try:
            os.replace(staged.staging_path, staged.result.target_file_path)
        except Exception:
            if staged.staging_path.exists():
                staged.staging_path.unlink()
            raise
    return staged.result


def stage_silver_dc_daily_partition_with_connection(
    *,
    lake_root_path: Path,
    connection,
    partition_key: str,
    staging_tag: str = "m6-repair",
) -> DcBoardSilverStagingResult:
    """Build and validate one dc_daily Silver staging file without promotion."""

    return _stage_silver_partition(
        dataset="dc_daily",
        lake_root_path=lake_root_path,
        connection=connection,
        partition_key=partition_key,
        staging_tag=staging_tag,
    )


def write_silver_dc_index_partition(*, lake_root_path: Path, duckdb: DuckDBResource, partition_key: str) -> DcBoardSilverWriteResult:
    return _write_silver_partition(
        dataset="dc_index",
        lake_root_path=lake_root_path,
        duckdb_resource=duckdb,
        partition_key=partition_key,
    )


def write_silver_dc_member_partition(*, lake_root_path: Path, duckdb: DuckDBResource, partition_key: str) -> DcBoardSilverWriteResult:
    return _write_silver_partition(
        dataset="dc_member",
        lake_root_path=lake_root_path,
        duckdb_resource=duckdb,
        partition_key=partition_key,
    )


def write_silver_dc_daily_partition(*, lake_root_path: Path, duckdb: DuckDBResource, partition_key: str) -> DcBoardSilverWriteResult:
    return _write_silver_partition(
        dataset="dc_daily",
        lake_root_path=lake_root_path,
        duckdb_resource=duckdb,
        partition_key=partition_key,
    )


def _materialize_result(result: DcBoardSilverWriteResult, schema: Sequence[object]) -> dg.MaterializeResult:
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=result.target_file_path,
            row_count=result.output_row_count,
            observed_columns=tuple(column.name for column in schema),
            extra_metadata=result.to_metadata(),
        )
    )


@dg.asset(
    name="silver_dc_index",
    partitions_def=cn_a_index_trade_days,
    deps=[raw_tushare_dc_index],
    group_name="board",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id="dc_index",
        source_system=SourceSystem.DERIVED,
        data_contract="standardized_dc_index_by_trade_date",
        column_schema=SILVER_DC_INDEX_SCHEMA,
        path_template=lake_path_template(
            silver_dc_index_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        extra_metadata={
            "partition_set": cn_a_index_trade_days.name,
            "source_asset": "raw_tushare_dc_index",
            "write_boundary": "m5_duckdb_set_based_atomic_replace",
        },
    ),
    description="从同日 raw_tushare_dc_index 生成规范化板块指数 Silver 分区。",
)
def silver_dc_index(context: dg.AssetExecutionContext, lake_root: LakeRootResource, duckdb: DuckDBResource) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    result = write_silver_dc_index_partition(
        lake_root_path=lake_root.root(), duckdb=duckdb, partition_key=context.partition_key
    )
    return _materialize_result(result, SILVER_DC_INDEX_SCHEMA)


@dg.asset(
    name="silver_dc_member",
    partitions_def=cn_a_index_trade_days,
    deps=[raw_tushare_dc_member],
    group_name="board",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id="dc_member",
        source_system=SourceSystem.DERIVED,
        data_contract="standardized_dc_member_by_trade_date",
        column_schema=SILVER_DC_MEMBER_SCHEMA,
        path_template=lake_path_template(
            silver_dc_member_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        extra_metadata={
            "partition_set": cn_a_index_trade_days.name,
            "source_asset": "raw_tushare_dc_member",
            "write_boundary": "m5_duckdb_set_based_atomic_replace",
        },
    ),
    description="从同日 raw_tushare_dc_member 生成规范化板块成员 Silver 分区。",
)
def silver_dc_member(context: dg.AssetExecutionContext, lake_root: LakeRootResource, duckdb: DuckDBResource) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    result = write_silver_dc_member_partition(
        lake_root_path=lake_root.root(), duckdb=duckdb, partition_key=context.partition_key
    )
    return _materialize_result(result, SILVER_DC_MEMBER_SCHEMA)


@dg.asset(
    name="silver_dc_daily",
    partitions_def=cn_a_index_trade_days,
    deps=[raw_tushare_dc_daily],
    group_name="board",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id="dc_daily",
        source_system=SourceSystem.DERIVED,
        data_contract="standardized_dc_daily_by_trade_date",
        column_schema=SILVER_DC_DAILY_SCHEMA,
        path_template=lake_path_template(
            silver_dc_daily_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        extra_metadata={
            "partition_set": cn_a_index_trade_days.name,
            "source_asset": "raw_tushare_dc_daily",
            "write_boundary": "m5_duckdb_set_based_atomic_replace",
        },
    ),
    description="从同日 raw_tushare_dc_daily 生成规范化板块行情 Silver 分区。",
)
def silver_dc_daily(context: dg.AssetExecutionContext, lake_root: LakeRootResource, duckdb: DuckDBResource) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    result = write_silver_dc_daily_partition(
        lake_root_path=lake_root.root(), duckdb=duckdb, partition_key=context.partition_key
    )
    return _materialize_result(result, SILVER_DC_DAILY_SCHEMA)


__all__ = [
    "DcBoardSilverValidationError",
    "DcBoardSilverStagingResult",
    "DcBoardSilverWriteResult",
    "silver_dc_daily",
    "silver_dc_index",
    "silver_dc_member",
    "stage_silver_dc_daily_partition_with_connection",
    "write_silver_dc_daily_partition",
    "write_silver_dc_index_partition",
    "write_silver_dc_member_partition",
]
