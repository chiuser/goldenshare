"""Dagster Raw assets for the Eastmoney board datasets.

The M3 writer module intentionally remains decorator-free.  This module is the
M4 Dagster boundary: it owns partition execution, candidate planning, and
materialization metadata, while delegating all source and staging work to the
bounded M3 writers.
"""

from collections.abc import Sequence
from datetime import date
from pathlib import Path
import re

import dagster as dg

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
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource, TushareResource
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
from orchestrator.defs.run_contracts.dc_board import (
    DC_BOARD_MAX_REQUESTS_PER_PARTITION,
    DC_DAILY_FIELDS,
    DC_DAILY_HISTORY_START_DATE,
    DC_INDEX_FIELDS,
    DC_INDEX_HISTORY_START_DATE,
    DC_MEMBER_FIELDS,
    DC_MEMBER_HISTORY_START_DATE,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)


_BOARD_CODE_RE = re.compile(r"^BK\d{4}\.DC$")


def _normalize_partition_key(partition_key: str) -> str:
    try:
        return date.fromisoformat(str(partition_key)).isoformat()
    except ValueError as exc:
        raise DcBoardRawValidationError(
            f"partition_key must be an ISO date: {partition_key!r}"
        ) from exc


def _asset_metadata(*, dataset_id: str, schema: Sequence[object], path: Path, source_api: str, partition_set: str) -> dict[str, object]:
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


def _first_expected_trade_date(connection, calendar_path: Path, min_trade_date: str) -> str:
    if not calendar_path.exists():
        raise DcBoardRawValidationError(
            f"dc_member candidate planning requires silver trade calendar: {calendar_path}"
        )
    row = connection.execute(
        """
        SELECT CAST(CAST(trade_date AS DATE) AS VARCHAR)
        FROM read_parquet(?)
        WHERE exchange = 'SSE'
          AND is_open = true
          AND CAST(trade_date AS DATE) >= CAST(? AS DATE)
        ORDER BY CAST(trade_date AS DATE)
        LIMIT 1
        """,
        [str(calendar_path), min_trade_date],
    ).fetchone()
    if row is None:
        raise DcBoardRawValidationError(
            f"no expected SSE trade date is available after {min_trade_date}"
        )
    return str(row[0])


def _previous_member_path(
    *,
    connection,
    lake_root_path: Path,
    target_trade_date: str,
    first_expected_trade_date: str,
) -> Path | None:
    if target_trade_date == first_expected_trade_date:
        return None
    rows = connection.execute(
        """
        SELECT CAST(CAST(trade_date AS DATE) AS VARCHAR)
        FROM read_parquet(?)
        WHERE exchange = 'SSE'
          AND is_open = true
          AND CAST(trade_date AS DATE) >= CAST(? AS DATE)
          AND CAST(trade_date AS DATE) < CAST(? AS DATE)
        ORDER BY CAST(trade_date AS DATE) DESC
        """,
        [
            str(silver_trade_calendar_path(lake_root_path)),
            DC_MEMBER_HISTORY_START_DATE,
            target_trade_date,
        ],
    ).fetchall()
    for row in rows:
        candidate_path = raw_dc_member_path(lake_root_path, str(row[0]))
        if candidate_path.exists():
            return candidate_path
    return None


def _previous_member_codes(connection, path: Path) -> tuple[str, ...]:
    rows = connection.execute(
        f"""
        SELECT DISTINCT trim(CAST(ts_code AS VARCHAR)) AS ts_code
        FROM {read_parquet(path)}
        WHERE ts_code IS NOT NULL AND trim(CAST(ts_code AS VARCHAR)) <> ''
        ORDER BY ts_code
        """
    ).fetchall()
    codes = tuple(str(row[0]).strip().upper() for row in rows)
    invalid = tuple(code for code in codes if not _BOARD_CODE_RE.fullmatch(code))
    if invalid:
        raise DcBoardRawValidationError(
            f"historical raw dc_member contains invalid board codes: {invalid[:10]}"
        )
    return codes


def plan_dc_member_candidate_codes(
    *,
    lake_root_path: Path,
    duckdb_resource: DuckDBResource,
    partition_key: str,
) -> tuple[str, ...]:
    """Build a bounded member request set from the index and nearest member file."""

    normalized_partition_key = _normalize_partition_key(partition_key)
    calendar_path = silver_trade_calendar_path(lake_root_path)
    with duckdb_resource.connect() as connection:
        index_codes = _target_raw_index_codes(
            connection,
            raw_dc_index_path(lake_root_path, normalized_partition_key),
        )
        first_expected = _first_expected_trade_date(
            connection,
            calendar_path,
            DC_MEMBER_HISTORY_START_DATE,
        )
        previous_path = _previous_member_path(
            connection=connection,
            lake_root_path=lake_root_path,
            target_trade_date=normalized_partition_key,
            first_expected_trade_date=first_expected,
        )
        if normalized_partition_key != first_expected and previous_path is None:
            raise DcBoardRawValidationError(
                "dc_member candidate planning has no historical member baseline "
                f"before {normalized_partition_key}"
            )
        previous_codes = _previous_member_codes(connection, previous_path) if previous_path else ()

    candidate_codes = tuple(sorted(set(index_codes).union(previous_codes)))
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
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = _normalize_partition_key(context.partition_key)
    result = write_dc_index_partition(
        lake_root_path=lake_root.root(),
        duckdb_resource=duckdb,
        tushare=tushare,
        partition_key=partition_key,
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
) -> dg.MaterializeResult:
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
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = _normalize_partition_key(context.partition_key)
    result = write_dc_daily_partition(
        lake_root_path=lake_root.root(),
        duckdb_resource=duckdb,
        tushare=tushare,
        partition_key=partition_key,
    )
    return _materialize_result(result, schema=RAW_TUSHARE_DC_DAILY_SCHEMA)


__all__ = [
    "plan_dc_member_candidate_codes",
    "raw_tushare_dc_daily",
    "raw_tushare_dc_index",
    "raw_tushare_dc_member",
]
