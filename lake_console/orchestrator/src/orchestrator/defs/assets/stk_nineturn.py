"""Dagster assets for the daily Tushare stock nine-turn dataset."""

import dagster as dg

from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_stk_nineturn_path,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_STK_NINETURN_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
)
from orchestrator.defs.stk_nineturn_contract import (
    RAW_STK_NINETURN_COLUMNS,
    RAW_STK_NINETURN_COLUMN_TYPES,
)
from orchestrator.defs.tushare_api_io import fetch_tushare_partition_to_raw
from orchestrator.utils.dg_log_helper import DgStdoutLogger


@dg.asset(
    name="raw_tushare_stk_nineturn",
    partitions_def=cn_a_stock_trade_days,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="stk_nineturn",
        source_system=SourceSystem.TUSHARE,
        source_api="stk_nineturn",
        source_category_path="股票数据 / 特色数据",
        source_doc="docs/sources/tushare/股票数据/特色数据/0364_神奇九转指标.md",
        data_contract="source_mirror",
        column_schema=RAW_TUSHARE_STK_NINETURN_SCHEMA,
        path_template=lake_path_template(
            raw_stk_nineturn_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        extra_metadata={
            "raw_contract": (
                "Tushare stk_nineturn source fields with trade_date stored as DATE; "
                "source stock codes remain unchanged."
            ),
            "daily_source": "tushare_api",
            "bootstrap_source": "prod_db_readonly",
            "write_summary": (
                "One trade-date partition is fetched with freq=daily and written "
                "through the shared paginated Tushare raw helper."
            ),
        },
    ),
    description=(
        "Tushare 神奇九转 raw 日分区源镜像。日常只从 Tushare stk_nineturn "
        "读取一个交易日，保留源代码和全部显式字段；历史初始化另走 prod DB bootstrap。"
    ),
)
def raw_tushare_stk_nineturn(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    target_path = raw_stk_nineturn_path(lake_root.root(), partition_key)
    log = DgStdoutLogger("stk_nineturn")
    log.stdout(
        "raw_stk_nineturn_started",
        partition_key=partition_key,
        source="tushare",
    )

    metadata = fetch_tushare_partition_to_raw(
        tushare=tushare,
        duckdb=duckdb,
        api_name="stk_nineturn",
        api_params={
            "trade_date": f"{partition_key} 00:00:00",
            "freq": "daily",
        },
        fields=RAW_STK_NINETURN_COLUMNS,
        column_types=RAW_STK_NINETURN_COLUMN_TYPES,
        target_path=target_path,
        partition_key=partition_key,
        allow_empty=False,
    )
    metadata.update(
        {
            "goldenshare/summary": "已写入神奇九转 raw 源镜像分区。",
            "goldenshare/next_action": (
                "等待 raw blocking checks 全部通过；通过后 Silver 才能消费。"
            ),
            "goldenshare/result_status": "written",
            "goldenshare/input_summary": {
                "source": "Tushare stk_nineturn",
                "partition_key": partition_key,
                "freq": "daily",
            },
            "goldenshare/diagnostic_ref": (
                "完整诊断看 raw stk_nineturn checks、materialization metadata "
                "和 run stdout。"
            ),
        }
    )
    log.stdout(
        "raw_stk_nineturn_completed",
        partition_key=partition_key,
        output_row_count=metadata.get("dagster/row_count"),
        page_count=metadata.get("goldenshare/page_count"),
    )
    return dg.MaterializeResult(metadata=metadata)
