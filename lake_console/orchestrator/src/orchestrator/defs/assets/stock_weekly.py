"""Adjusted weekly Raw delivered by immutable Prod batches."""

from pathlib import Path
from time import monotonic

import dagster as dg

from orchestrator.defs.partitions import cn_a_stock_week_ends
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_stk_period_bar_adj_week_path,
)
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_STK_PERIOD_BAR_ADJ_WEEK_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.configs import StockWeeklyAdjProdConfig
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    weekly_data_contract,
    weekly_dataset_id,
    weekly_source_api,
    weekly_source_doc,
)
from orchestrator.defs.stock_weekly_adj_run import deliver_closed_adjusted_batch


def _cancel_probe(context):
    checked_at, canceled = 0.0, False

    def cancel():
        nonlocal checked_at, canceled
        if monotonic() - checked_at >= 2:
            checked_at = monotonic()
            run = context.instance.get_run_by_id(context.run.run_id)
            canceled = run is not None and run.status in (
                dg.DagsterRunStatus.CANCELING, dg.DagsterRunStatus.CANCELED,
            )
        return canceled

    return cancel


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
    config: StockWeeklyAdjProdConfig,
    lake_root: LakeRootResource,
):
    """从Prod接收已闭合复权周线批；同键覆盖全部源字段，保留未返回的历史行。"""
    lake_root.ensure_available_for_run()
    yield from deliver_closed_adjusted_batch(
        context, config, target_root=lake_root.root(),
        staging_root=Path(DEFAULT_LAKE_STAGING_ROOT),
        cancel=_cancel_probe(context), progress=lambda p: context.log.info(str(p)),
    )
