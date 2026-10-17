"""Adjusted weekly Raw delivered directly from the period source."""

import dagster as dg

from orchestrator.defs.partitions import cn_a_stock_week_ends
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_stk_period_bar_adj_week_path,
    silver_stock_weekly_path,
)
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_STK_PERIOD_BAR_ADJ_WEEK_SCHEMA,
    SILVER_STOCK_WEEKLY_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.configs import StockPeriodRawConfig
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
)
from orchestrator.defs.run_contracts.stock_period_silver import StockPeriodSilverConfig
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    weekly_data_contract,
    weekly_dataset_id,
    weekly_source_api,
    weekly_source_doc,
)
from orchestrator.defs.stock_period_silver import deliver_asset as deliver_silver_asset
from orchestrator.defs.stock_period_update import deliver_asset


@dg.asset(
    partitions_def=cn_a_stock_week_ends,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id=weekly_dataset_id(StockWeeklySource.PRIMARY_ADJUSTED),
        source_system=SourceSystem.TUSHARE,
        data_contract=weekly_data_contract(StockWeeklySource.PRIMARY_ADJUSTED),
        column_schema=RAW_STK_PERIOD_BAR_ADJ_WEEK_SCHEMA,
        path_template=lake_path_template(
            raw_stk_period_bar_adj_week_path(
                PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY
            )
        ),
        source_api=weekly_source_api(StockWeeklySource.PRIMARY_ADJUSTED),
        source_category_path="股票数据/行情数据",
        source_doc=weekly_source_doc(StockWeeklySource.PRIMARY_ADJUSTED),
    ),
)
def raw_tushare_stk_period_bar_adj_week(
    context: dg.AssetExecutionContext,
    config: StockPeriodRawConfig,
    lake_root: LakeRootResource,
) -> dg.MaterializeResult:
    return deliver_asset(context, config, lake_root, "week")


@dg.asset(
    partitions_def=cn_a_stock_week_ends,
    deps=[
        "raw_tushare_stk_period_bar_adj_week",
        "silver_stock_lifecycle",
        "silver_stock_identity_map",
    ],
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="stock_weekly",
        source_system=SourceSystem.DERIVED,
        data_contract="stock_weekly@1",
        column_schema=SILVER_STOCK_WEEKLY_SCHEMA,
        path_template=lake_path_template(
            silver_stock_weekly_path(
                PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY
            )
        ),
    ),
)
def silver_stock_weekly(
    context: dg.AssetExecutionContext,
    config: StockPeriodSilverConfig,
    lake_root: LakeRootResource,
) -> dg.MaterializeResult:
    """Keep source rows and fields inside the explicitly approved audit scope."""
    return deliver_silver_asset(context, config, lake_root, "week")
