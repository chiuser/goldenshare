"""Tushare daily-basic raw snapshot, with no Silver transformation."""

from pathlib import Path

import dagster as dg

from orchestrator.defs.asset_guards.daily_basic_readiness import (
    load_daily_basic_input_codes,
)
from orchestrator.defs.daily_basic_contract import DAILY_BASIC_FIELDS
from orchestrator.defs.daily_basic_raw_io import write_daily_basic_partition
from orchestrator.defs.partitions import cn_a_daily_basic_trade_days
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_daily_basic_path,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
)
from orchestrator.defs.run_contracts.asset_column_schemas import RAW_DAILY_BASIC_SCHEMA
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.configs import DailyBasicRawConfig
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.utils.dg_log_helper import DgStdoutLogger


@dg.asset(
    partitions_def=cn_a_daily_basic_trade_days,
    deps=[
        dg.AssetDep(
            "raw_tushare_stock_daily", partition_mapping=dg.IdentityPartitionMapping()
        )
    ],
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.QUOTE_DATA),
    description="按交易日保留Tushare股票每日指标18字段，覆盖同日股票Raw日线，额外代码原样保留。",
    metadata=build_asset_definition_metadata(
        dataset_id="daily_basic",
        source_system=SourceSystem.TUSHARE,
        data_contract="tushare_daily_basic_by_date",
        column_schema=RAW_DAILY_BASIC_SCHEMA,
        path_template=lake_path_template(
            raw_daily_basic_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        source_api="daily_basic",
        source_category_path="股票数据/行情数据",
        source_doc="docs/sources/tushare/股票数据/行情数据/0032_每日指标.md",
    ),
)
def raw_tushare_daily_basic(
    context: dg.AssetExecutionContext,
    config: DailyBasicRawConfig,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    logger = DgStdoutLogger("daily_basic")
    logger.stdout("daily_basic_started", partition_key=context.partition_key)

    def load_codes():
        with duckdb.connect() as connection:
            return load_daily_basic_input_codes(
                context.instance, connection, lake_root.root(), context.partition_key
            )

    result = write_daily_basic_partition(
        lake_root=lake_root.root(),
        staging_root=Path(DEFAULT_LAKE_STAGING_ROOT),
        trade_date=context.partition_key,
        run_id=context.run.run_id,
        duckdb_resource=duckdb,
        tushare=tushare,
        load_expected_codes=load_codes,
        write_mode=config.write_mode,
    )
    logger.stdout(
        "daily_basic_completed",
        partition_key=context.partition_key,
        row_count=result["source_row_count"],
        request_count=result["request_count"],
    )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=raw_daily_basic_path(lake_root.root(), context.partition_key),
            row_count=result["source_row_count"],
            observed_columns=DAILY_BASIC_FIELDS,
            extra_metadata={
                **result,
                "summary": "每日指标已交付，保留源端18字段和额外代码。",
                "next_action": "等待两项检查通过后使用。",
            },
        )
    )
