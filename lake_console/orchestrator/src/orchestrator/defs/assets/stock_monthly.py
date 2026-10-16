"""Adjusted monthly Raw preserving all three source price forms."""

import dagster as dg

from orchestrator.defs.partitions import cn_a_stock_months
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_stock_monthly_path,
)
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_STK_PERIOD_BAR_ADJ_MONTH_SCHEMA,
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
from orchestrator.defs.run_contracts.stock_monthly import (
    StockMonthlySource,
    monthly_data_contract,
    monthly_dataset_id,
    monthly_source_api,
    monthly_source_doc,
)
from orchestrator.defs.stock_period_update import deliver_asset


@dg.asset(
    partitions_def=cn_a_stock_months,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id=monthly_dataset_id(StockMonthlySource.PRIMARY_ADJUSTED),
        source_system=SourceSystem.TUSHARE,
        data_contract=monthly_data_contract(StockMonthlySource.PRIMARY_ADJUSTED),
        column_schema=RAW_STK_PERIOD_BAR_ADJ_MONTH_SCHEMA,
        path_template=lake_path_template(
            raw_stock_monthly_path(
                PATH_TEMPLATE_LAKE_ROOT,
                StockMonthlySource.PRIMARY_ADJUSTED,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        source_api=monthly_source_api(StockMonthlySource.PRIMARY_ADJUSTED),
        source_category_path="股票数据/行情数据",
        source_doc=monthly_source_doc(StockMonthlySource.PRIMARY_ADJUSTED),
    ),
)
def raw_tushare_stk_period_bar_adj_month(
    context: dg.AssetExecutionContext,
    config: StockPeriodRawConfig,
    lake_root: LakeRootResource,
) -> dg.MaterializeResult:
    return deliver_asset(context, config, lake_root, "month")
