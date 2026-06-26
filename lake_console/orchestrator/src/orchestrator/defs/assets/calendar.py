import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import (
    TRADE_CALENDAR_RAW_REQUIRED_COLUMNS,
    copy_query_to_parquet,
    count_parquet_query,
    describe_parquet_query,
    silver_trade_calendar_select,
)
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    lake_path_template,
    raw_trade_calendar_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_TRADE_CALENDAR_SCHEMA,
    SILVER_TRADE_CALENDAR_SCHEMA,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.tushare_api_io import fetch_tushare_full_file_to_raw
from orchestrator.utils.dg_log_helper import DgStdoutLogger


CN_A_TIMEZONE = ZoneInfo("Asia/Shanghai")
TRADE_CALENDAR_START_DATE = "19900101"
TRADE_CALENDAR_RAW_COLUMN_TYPES = {
    column.name: column.type for column in RAW_TUSHARE_TRADE_CALENDAR_SCHEMA
}
LOGGER = DgStdoutLogger("basic_facts.trade_calendar")


def _column_names(
    connection, path: Path, *, hive_partitioning: bool = False
) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=hive_partitioning)
    ).fetchall()
    return [row[0] for row in rows]


def _row_count(connection, path: Path, *, hive_partitioning: bool = False) -> int:
    return int(
        connection.execute(
            count_parquet_query(path, hive_partitioning=hive_partitioning)
        ).fetchone()[0]
    )


def _replace_parquet_from_query(connection, select_sql: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f"{target_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    connection.execute(copy_query_to_parquet(select_sql, temporary_path))
    os.replace(temporary_path, target_path)


@dg.asset(
    name="raw_tushare_trade_calendar",
    group_name="calendar",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.BASIC_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="trade_cal",
        source_system=SourceSystem.TUSHARE,
        source_api="trade_cal",
        source_category_path="股票数据 / 基础数据",
        source_doc="docs/sources/tushare/股票数据/基础数据/0026_交易日历.md",
        data_contract="source_mirror",
        column_schema=RAW_TUSHARE_TRADE_CALENDAR_SCHEMA,
        path_template=lake_path_template(
            raw_trade_calendar_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
        extra_metadata={
            "raw_contract": "cal_date/pretrade_date YYYYMMDD string, is_open 0/1 integer",
            "update_policy": "low_frequency_full_file_api_update",
        },
    ),
    description=(
        "Tushare 交易日历 raw 源镜像，保存上交所交易日历原始字段，"
        "供标准交易日历和全市场日频资产判断交易日使用。"
    ),
)
def raw_tushare_trade_calendar(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    end_date = f"{datetime.now(CN_A_TIMEZONE).year}1231"
    target_path = raw_trade_calendar_path(lake_root.root())
    LOGGER.stdout(
        "trade_calendar_raw_started",
        start_date=TRADE_CALENDAR_START_DATE,
        end_date=end_date,
    )
    metadata = fetch_tushare_full_file_to_raw(
        tushare=tushare,
        duckdb=duckdb,
        api_name="trade_cal",
        api_params={
            "exchange": "SSE",
            "start_date": TRADE_CALENDAR_START_DATE,
            "end_date": end_date,
        },
        fields=TRADE_CALENDAR_RAW_REQUIRED_COLUMNS,
        column_types=TRADE_CALENDAR_RAW_COLUMN_TYPES,
        target_path=target_path,
        allow_empty=False,
    )
    LOGGER.stdout(
        "trade_calendar_raw_completed",
        row_count=metadata.get("dagster/row_count"),
        end_date=end_date,
    )

    return dg.MaterializeResult(
        metadata={
            **metadata,
            **build_materialization_metadata(
                extra_metadata={
                    "summary": (
                        f"已写入上交所交易日历 raw 快照，覆盖 "
                        f"{TRADE_CALENDAR_START_DATE} 至 {end_date}。"
                    ),
                    "next_action": "等待 raw blocking check 通过后生成 silver_trade_calendar。",
                    "result_status": "written",
                    "input_summary": "来源为 Tushare trade_cal，全量刷新上交所日历。",
                    "filter_summary": "raw 层不做业务过滤，保留源站显式字段。",
                    "diagnostic_ref": "完整字段和质量规则看 raw_trade_calendar_contract_check。",
                    "calendar_start_date": TRADE_CALENDAR_START_DATE,
                    "calendar_end_date": end_date,
                }
            ),
        }
    )


@dg.asset(
    name="silver_trade_calendar",
    deps=["raw_tushare_trade_calendar"],
    group_name="calendar",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.BASIC_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="trade_cal",
        source_system=SourceSystem.DERIVED,
        data_contract="standardized_trade_calendar",
        column_schema=SILVER_TRADE_CALENDAR_SCHEMA,
        path_template=lake_path_template(
            silver_trade_calendar_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
    ),
    description=(
        "A 股交易日历 silver 标准事实，按上交所交易日口径输出标准日期字段，"
        "供日频资产分区注册、freshness 和 readiness 判断使用。"
    ),
)
def silver_trade_calendar(
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    raw_path = raw_trade_calendar_path(lake_root.root())
    target_path = silver_trade_calendar_path(lake_root.root())
    if not raw_path.exists():
        raise FileNotFoundError(f"Missing raw trade calendar file: {raw_path}")

    LOGGER.stdout("trade_calendar_silver_started")
    with connect_configured_duckdb() as connection:
        _replace_parquet_from_query(
            connection,
            silver_trade_calendar_select(raw_path),
            target_path,
        )
        columns = _column_names(connection, target_path, hive_partitioning=False)
        row_count = _row_count(connection, target_path, hive_partitioning=False)
    LOGGER.stdout("trade_calendar_silver_completed", row_count=row_count)

    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=target_path,
            row_count=row_count,
            observed_columns=columns,
            extra_metadata={
                "summary": "已生成 A 股标准交易日历，供日频资产判断交易日和分区。",
                "next_action": "等待 silver_trade_calendar blocking checks 通过后供下游消费。",
                "result_status": "written",
                "input_summary": "输入为 raw_tushare_trade_calendar 全量文件。",
                "filter_summary": "标准化日期和开市标记，不改变交易日历业务口径。",
                "diagnostic_ref": "完整诊断看 silver_trade_calendar checks 和 run stdout。",
            },
        )
    )
