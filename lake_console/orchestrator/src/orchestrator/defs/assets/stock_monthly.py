"""Two independent source-preserving monthly Raw assets."""

from pathlib import Path
from time import monotonic

import dagster as dg

from orchestrator.defs.partitions import cn_a_stock_months
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_stock_monthly_path,
)
from orchestrator.defs.resources import LakeRootResource, TushareResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_STK_PERIOD_BAR_ADJ_MONTH_SCHEMA,
    RAW_STK_PERIOD_BAR_MONTH_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.configs import StockMonthlyRawConfig
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.run_contracts.stock_monthly import (
    StockMonthlySource,
    monthly_column_specs,
    monthly_data_contract,
    monthly_dataset_id,
    monthly_source_api,
    monthly_source_doc,
)
from orchestrator.defs.stock_monthly_point import (
    StockMonthlyPointWorker,
    deliver_month_intent,
)
from orchestrator.defs.stock_monthly_update_state import monthly_upstream_bindings


def _deliver(context, config, lake_root, tushare, source):
    lake_root.ensure_available_for_run()
    checked_at, canceled = 0.0, False

    def cancel():
        nonlocal checked_at, canceled
        if monotonic() - checked_at >= 2:
            checked_at = monotonic()
            run = context.instance.get_run_by_id(context.run.run_id)
            canceled = run is not None and run.status in (
                dg.DagsterRunStatus.CANCELING,
                dg.DagsterRunStatus.CANCELED,
            )
        return canceled

    try:
        result = deliver_month_intent(
            source,
            context.partition_key,
            target_root=lake_root.root(),
            staging_root=Path(DEFAULT_LAKE_STAGING_ROOT),
            worker=StockMonthlyPointWorker(tushare.token, source),
            execution_id=context.run.run_id,
            automatic_intent_date=config.automatic_intent_date,
            upstream_bindings=lambda days: monthly_upstream_bindings(
                context.instance, days
            ),
            cancel=cancel,
            progress=lambda p: context.log.info(str(p)),
        )
    except (ValueError, OSError) as error:
        label = "复权" if source is StockMonthlySource.PRIMARY_ADJUSTED else "未复权"
        raise dg.Failure(
            description=f"{context.partition_key}股票{label}月线交付停止：{error}。核查日线、身份checks及冻结的源页证明；源未就绪等待下一日19:30，或使用原配置显式续跑。异值须单独审阅并批准修订，备用源不自动调用。"
        ) from None
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=result["path"],
            row_count=result["rows"],
            observed_columns=tuple(n for n, _ in monthly_column_specs(source)),
            extra_metadata={"goldenshare/monthly_delivery": result},
        )
    )


@dg.asset(
    partitions_def=cn_a_stock_months,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id=monthly_dataset_id(StockMonthlySource.PRIMARY_UNADJUSTED),
        source_system=SourceSystem.TUSHARE,
        data_contract=monthly_data_contract(StockMonthlySource.PRIMARY_UNADJUSTED),
        column_schema=RAW_STK_PERIOD_BAR_MONTH_SCHEMA,
        path_template=lake_path_template(
            raw_stock_monthly_path(
                PATH_TEMPLATE_LAKE_ROOT,
                StockMonthlySource.PRIMARY_UNADJUSTED,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        source_api=monthly_source_api(StockMonthlySource.PRIMARY_UNADJUSTED),
        source_category_path="股票数据/行情数据",
        source_doc=monthly_source_doc(StockMonthlySource.PRIMARY_UNADJUSTED),
    ),
)
def raw_tushare_stk_period_bar_month(
    context: dg.AssetExecutionContext,
    config: StockMonthlyRawConfig,
    lake_root: LakeRootResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    return _deliver(
        context, config, lake_root, tushare, StockMonthlySource.PRIMARY_UNADJUSTED
    )


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
    config: StockMonthlyRawConfig,
    lake_root: LakeRootResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    return _deliver(
        context, config, lake_root, tushare, StockMonthlySource.PRIMARY_ADJUSTED
    )
