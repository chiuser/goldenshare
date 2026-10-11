"""Dagster Raw assets for the Eastmoney board datasets.

The M3 writer module intentionally remains decorator-free.  This module is the
M4 Dagster boundary: it owns partition execution, candidate planning, and
materialization metadata, while delegating all source and staging work to the
bounded M3 writers.
"""

import re
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

import dagster as dg

from orchestrator.defs.asset_guards.dc_board_run_recovery import (
    validate_dc_running_identity,
)
from orchestrator.defs.asset_guards.dc_board_source_probe import (
    DcBoardSourceValidationError,
)
from orchestrator.defs.assets.dc_board import (
    DcBoardRawValidationError,
    write_dc_daily_partition,
    write_dc_index_partition,
    write_dc_member_partition,
)
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.partitions import (
    cn_a_dc_daily_trade_days,
    cn_a_dc_index_trade_days,
    cn_a_dc_member_trade_days,
)
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_dc_daily_path,
    raw_dc_index_path,
    raw_dc_member_path,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    ProdPostgresResource,
    TushareResource,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_DC_DAILY_SCHEMA,
    RAW_TUSHARE_DC_INDEX_SCHEMA,
    RAW_TUSHARE_DC_MEMBER_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.configs import (
    DcBoardRawRunConfig,
    validate_dc_board_source_freeze_config,
)
from orchestrator.defs.run_contracts.dc_board import (
    DC_BOARD_MAX_REQUESTS_PER_PARTITION,
)
from orchestrator.defs.run_contracts.dc_board_failures import (
    DcBoardFailureFacts,
    DcBoardRequestFailure,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)


@contextmanager
def _raw_execution_boundary(context, config: DcBoardRawRunConfig, *, asset_name: str):
    try:
        validate_dc_running_identity(context, config.recovery_identity, asset_name=asset_name,
                                     now=datetime.now(UTC))
        validate_dc_board_source_freeze_config(config.source_proof,
            partition_key=context.partition_key, asset_name=asset_name)
        yield config.source_proof
    except Exception as exc:
        if isinstance(exc, DcBoardRequestFailure):
            facts = exc.facts
        elif isinstance(exc, DcBoardSourceValidationError):
            facts = DcBoardFailureFacts(reason_code=exc.reason_code)
        elif isinstance(exc, DcBoardRawValidationError):
            facts = DcBoardFailureFacts(reason_code="source_or_data_contract")
        else:
            facts = DcBoardFailureFacts(reason_code="unknown_or_infrastructure")
        raise dg.Failure(description="DC Raw execution failed: " + facts.reason_code,
                         metadata=facts.metadata(), allow_retries=False) from exc


_BOARD_CODE_RE = re.compile(r"^BK\d{4}\.DC$")


def _normalize_partition_key(partition_key: str) -> str:
    try:
        return date.fromisoformat(str(partition_key)).isoformat()
    except ValueError as exc:
        raise DcBoardRawValidationError(
            f"partition_key must be an ISO date: {partition_key!r}"
        ) from exc


def _asset_metadata(
    *,
    dataset_id: str,
    schema: Sequence[object],
    path: Path,
    source_api: str,
    partition_set: str,
) -> dict[str, object]:
    return build_asset_definition_metadata(
        dataset_id=dataset_id,
        source_system=SourceSystem.TUSHARE,
        data_contract=f"tushare_{dataset_id}_raw_by_trade_date",
        column_schema=schema,
        path_template=lake_path_template(path),
        source_api=source_api,
        extra_metadata={
            "partition_set": partition_set,
            "write_boundary": "m3_bounded_writer",
        },
    )


def _materialize_result(result, *, schema: Sequence[object]) -> dg.MaterializeResult:
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=result.target_path,
            row_count=result.written_row_count,
            observed_columns=tuple(column.name for column in schema),
            extra_metadata=result.to_metadata(),
        )
    )


def _target_raw_index_codes(connection, path: Path) -> tuple[str, ...]:
    if not path.exists():
        raise DcBoardRawValidationError(
            f"dc_member candidate planning requires raw dc_index: {path}"
        )
    rows = connection.execute(
        f"""
        SELECT DISTINCT trim(CAST(ts_code AS VARCHAR)) AS ts_code
        FROM {read_parquet(path)}
        WHERE ts_code IS NOT NULL AND trim(CAST(ts_code AS VARCHAR)) <> ''
        ORDER BY ts_code
        """
    ).fetchall()
    codes = tuple(str(row[0]).strip().upper() for row in rows)
    if not codes:
        raise DcBoardRawValidationError(
            f"dc_member candidate planning found no board codes in {path}"
        )
    invalid = tuple(code for code in codes if not _BOARD_CODE_RE.fullmatch(code))
    if invalid:
        raise DcBoardRawValidationError(
            f"raw dc_index contains invalid board codes: {invalid[:10]}"
        )
    return codes


def plan_dc_member_candidate_codes(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    partition_key: str,
) -> tuple[str, ...]:
    """Use only the same-day raw index directory as the member request set."""

    normalized_partition_key = _normalize_partition_key(partition_key)
    with duckdb_resource.connect() as connection:
        index_codes = _target_raw_index_codes(
            connection,
            raw_dc_index_path(lake_root_path, normalized_partition_key),
        )

    candidate_codes = tuple(sorted(set(index_codes)))
    if len(candidate_codes) > DC_BOARD_MAX_REQUESTS_PER_PARTITION:
        raise DcBoardRawValidationError(
            "dc_member candidate count exceeds request budget before Tushare calls: "
            f"{len(candidate_codes)} > {DC_BOARD_MAX_REQUESTS_PER_PARTITION}"
        )
    return candidate_codes


@dg.asset(
    name="raw_tushare_dc_index",
    partitions_def=cn_a_dc_index_trade_days,
    group_name="board",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id="dc_index",
        source_system=SourceSystem.TUSHARE,
        data_contract="tushare_dc_index_raw_by_trade_date",
        column_schema=RAW_TUSHARE_DC_INDEX_SCHEMA,
        path_template=lake_path_template(
            raw_dc_index_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        source_api="dc_index",
        extra_metadata={
            "partition_set": cn_a_dc_index_trade_days.name,
            "write_boundary": "m3_bounded_writer",
        },
    ),
    description="按交易日从 Tushare 同步东方财富板块指数 raw 分区。",
)
def raw_tushare_dc_index(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
    prod_postgres: ProdPostgresResource,
    config: DcBoardRawRunConfig,
) -> dg.MaterializeResult:
    with _raw_execution_boundary(context, config, asset_name="raw_tushare_dc_index") as proof:
        lake_root.ensure_available_for_run()
        partition_key = _normalize_partition_key(context.partition_key)
        result = write_dc_index_partition(
            lake_root_path=lake_root.root(),
            duckdb_resource=duckdb,
            tushare=tushare,
            prod_postgres=prod_postgres,
            partition_key=partition_key,
            source_snapshot_config=proof,
        )
        return _materialize_result(result, schema=RAW_TUSHARE_DC_INDEX_SCHEMA)


@dg.asset(
    name="raw_tushare_dc_member",
    partitions_def=cn_a_dc_member_trade_days,
    deps=["raw_tushare_dc_index"],
    group_name="board",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id="dc_member",
        source_system=SourceSystem.TUSHARE,
        data_contract="tushare_dc_member_raw_by_trade_date",
        column_schema=RAW_TUSHARE_DC_MEMBER_SCHEMA,
        path_template=lake_path_template(
            raw_dc_member_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        source_api="dc_member",
        extra_metadata={
            "partition_set": cn_a_dc_member_trade_days.name,
            "write_boundary": "m3_bounded_writer",
        },
    ),
    description="按交易日和板块代码从 Tushare 同步东方财富板块成员 raw 分区。",
)
def raw_tushare_dc_member(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
    prod_postgres: ProdPostgresResource,
    config: DcBoardRawRunConfig,
) -> dg.MaterializeResult:
    with _raw_execution_boundary(context, config, asset_name="raw_tushare_dc_member") as proof:
        lake_root.ensure_available_for_run()
        partition_key = _normalize_partition_key(context.partition_key)
        candidate_codes = plan_dc_member_candidate_codes(
            lake_root_path=lake_root.root(),
            duckdb_resource=duckdb,
            partition_key=partition_key,
        )
        result = write_dc_member_partition(
            lake_root_path=lake_root.root(),
            duckdb_resource=duckdb,
            tushare=tushare,
            prod_postgres=prod_postgres,
            source_snapshot_config=proof,
            partition_key=partition_key,
            candidate_codes=candidate_codes,
        )
        return _materialize_result(result, schema=RAW_TUSHARE_DC_MEMBER_SCHEMA)


@dg.asset(
    name="raw_tushare_dc_daily",
    partitions_def=cn_a_dc_daily_trade_days,
    group_name="board",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id="dc_daily",
        source_system=SourceSystem.TUSHARE,
        data_contract="tushare_dc_daily_raw_by_trade_date",
        column_schema=RAW_TUSHARE_DC_DAILY_SCHEMA,
        path_template=lake_path_template(
            raw_dc_daily_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        source_api="dc_daily",
        extra_metadata={
            "partition_set": cn_a_dc_daily_trade_days.name,
            "write_boundary": "m3_bounded_writer",
        },
    ),
    description="按交易日从 Tushare 同步东方财富板块行情 raw 分区。",
)
def raw_tushare_dc_daily(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
    prod_postgres: ProdPostgresResource,
    config: DcBoardRawRunConfig,
) -> dg.MaterializeResult:
    with _raw_execution_boundary(context, config, asset_name="raw_tushare_dc_daily") as proof:
        lake_root.ensure_available_for_run()
        partition_key = _normalize_partition_key(context.partition_key)
        result = write_dc_daily_partition(
            lake_root_path=lake_root.root(),
            duckdb_resource=duckdb,
            tushare=tushare,
            prod_postgres=prod_postgres,
            source_snapshot_config=proof,
            partition_key=partition_key,
        )
        return _materialize_result(result, schema=RAW_TUSHARE_DC_DAILY_SCHEMA)


__all__ = [
    "plan_dc_member_candidate_codes",
    "raw_tushare_dc_daily",
    "raw_tushare_dc_index",
    "raw_tushare_dc_member",
]
