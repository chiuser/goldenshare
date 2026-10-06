"""Three independent source-preserving weekly Raw assets."""

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
    raw_stk_period_bar_week_path,
    raw_tushare_weekly_path,
)
from orchestrator.defs.resources import LakeRootResource, TushareResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_STK_PERIOD_BAR_ADJ_WEEK_SCHEMA,
    RAW_STK_PERIOD_BAR_WEEK_SCHEMA,
    RAW_TUSHARE_WEEKLY_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.configs import StockWeeklyRawConfig
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    weekly_column_specs,
    weekly_data_contract,
    weekly_dataset_id,
    weekly_source_api,
    weekly_source_doc,
)
from orchestrator.defs.stock_weekly_point import (
    StockWeeklyPointWorker,
    deliver_stock_weekly_point,
)
from orchestrator.defs.stock_weekly_update_execution import WeeklyUpdateExecution
from orchestrator.defs.stock_weekly_update_state import weekly_upstream_events_ready


def _deliver(context, config, lake_root, tushare, source):
    update = None
    if config.automatic_intent_date is not None:
        if (
            source is StockWeeklySource.ALTERNATE_WEEKLY
            or config.code_list_path is not None
        ):
            raise ValueError("alternate_or_code_list_automatic_forbidden")
        update = WeeklyUpdateExecution(
            source,
            context.partition_key,
            config.automatic_intent_date,
            target_root=lake_root.root(),
            upstream_ready=lambda days: weekly_upstream_events_ready(
                context.instance, days
            ),
        )
    lake_root.ensure_available_for_run()
    checked_at, canceled = 0.0, False

    def cancel():
        nonlocal checked_at, canceled
        if monotonic() - checked_at >= 2:
            checked_at = monotonic()
            run = context.instance.get_run_by_id(context.run_id)
            canceled = run is not None and run.status in (
                dg.DagsterRunStatus.CANCELING,
                dg.DagsterRunStatus.CANCELED,
            )
        return canceled

    result = deliver_stock_weekly_point(
        source,
        context.partition_key,
        target_root=lake_root.root(),
        staging_root=Path(DEFAULT_LAKE_STAGING_ROOT),
        worker=StockWeeklyPointWorker(tushare.token, source),
        code_list_path=config.code_list_path,
        progress=lambda p: context.log.info(str(p)),
        cancel=cancel,
        update=update,
    )
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=result["path"],
            row_count=result["rows"],
            observed_columns=tuple(n for n, _, _ in weekly_column_specs(source)),
        )
    )


@dg.asset(
    partitions_def=cn_a_stock_week_ends,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id=weekly_dataset_id(StockWeeklySource.PRIMARY_UNADJUSTED),
        source_system=SourceSystem.TUSHARE,
        data_contract=weekly_data_contract(StockWeeklySource.PRIMARY_UNADJUSTED),
        column_schema=RAW_STK_PERIOD_BAR_WEEK_SCHEMA,
        path_template=lake_path_template(
            raw_stk_period_bar_week_path(
                PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY
            )
        ),
        source_api=weekly_source_api(StockWeeklySource.PRIMARY_UNADJUSTED),
        source_category_path="股票数据/行情数据",
        source_doc=weekly_source_doc(StockWeeklySource.PRIMARY_UNADJUSTED),
    ),
)
def raw_tushare_stk_period_bar_week(
    context: dg.AssetExecutionContext,
    config: StockWeeklyRawConfig,
    lake_root: LakeRootResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    return _deliver(
        context, config, lake_root, tushare, StockWeeklySource.PRIMARY_UNADJUSTED
    )


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
    config: StockWeeklyRawConfig,
    lake_root: LakeRootResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    return _deliver(
        context, config, lake_root, tushare, StockWeeklySource.PRIMARY_ADJUSTED
    )


@dg.asset(
    partitions_def=cn_a_stock_week_ends,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id=weekly_dataset_id(StockWeeklySource.ALTERNATE_WEEKLY),
        source_system=SourceSystem.TUSHARE,
        data_contract=weekly_data_contract(StockWeeklySource.ALTERNATE_WEEKLY),
        column_schema=RAW_TUSHARE_WEEKLY_SCHEMA,
        path_template=lake_path_template(
            raw_tushare_weekly_path(
                PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY
            )
        ),
        source_api=weekly_source_api(StockWeeklySource.ALTERNATE_WEEKLY),
        source_category_path="股票数据/行情数据",
        source_doc=weekly_source_doc(StockWeeklySource.ALTERNATE_WEEKLY),
    ),
)
def raw_tushare_weekly(
    context: dg.AssetExecutionContext,
    config: StockWeeklyRawConfig,
    lake_root: LakeRootResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    return _deliver(
        context, config, lake_root, tushare, StockWeeklySource.ALTERNATE_WEEKLY
    )
