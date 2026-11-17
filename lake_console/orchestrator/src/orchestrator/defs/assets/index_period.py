"""按周期管理、每频率保存完整历史的主要指数 Raw 资产。"""

from pathlib import Path

import dagster as dg

from orchestrator.defs.checks.index_period_checks import (
    IndexPeriodContractError,
    index_period_raw_check_result,
    index_period_raw_check_spec,
    index_period_silver_check_result,
    index_period_silver_check_spec,
)
from orchestrator.defs.io.index_period_writer import (
    write_index_period_raw,
    write_index_period_silver,
)
from orchestrator.defs.partitions import cn_a_index_months, cn_a_index_week_ends
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    PATH_TEMPLATE_LAKE_ROOT,
    index_period_candidate_path,
    lake_path_template,
    raw_index_monthly_path,
    raw_index_weekly_path,
    silver_index_daily_path,
    silver_index_monthly_path,
    silver_index_weekly_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_WEEKLY_SCHEMA,
    SILVER_INDEX_WEEKLY_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.index_period import (
    INDEX_MONTHLY,
    INDEX_WEEKLY,
    IndexPeriodSilverConfig,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.run_contracts.run_keys import build_batch_id
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    partition_dataset_readiness_status_from_latest_checks,
)


def _update_raw_index_period(context, period):
    context.resources.lake_root.ensure_available_for_run()
    context.log.info(
        "开始下载并更新%s，分区%s", period.dataset_id, context.partition_key
    )
    try:
        with context.resources.duckdb.connect() as connection:
            result = write_index_period_raw(
                connection,
                lake_root=context.resources.lake_root.root(),
                period=period,
                partition_key=context.partition_key,
                run_id=context.run.run_id,
                staging_root=Path(DEFAULT_LAKE_STAGING_ROOT),
            )
    except IndexPeriodContractError as error:
        yield index_period_raw_check_result(
            period,
            error.result,
            partition_key=context.partition_key,
            period_end=error.period_end,
            path=index_period_candidate_path(
                Path(DEFAULT_LAKE_STAGING_ROOT),
                context.run.run_id,
                "raw",
                period.dataset_id,
            ),
        )
        raise dg.Failure(str(error)) from error
    context.log.info(
        "%s候选已校验并提升，本分区%d行", period.dataset_id, result.partition_row_count
    )
    yield dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=result.path,
            row_count=result.partition_row_count,
            observed_columns=[column.name for column in RAW_INDEX_WEEKLY_SCHEMA],
            extra_metadata={
                "partition_key": context.partition_key,
                "period_end": result.period_end.isoformat(),
                "frequency": period.frequency,
                "source_row_count": result.check.source_row_count,
                "changed_row_count": result.check.source_row_count,
                "file_row_count": result.check.file_row_count,
                "upstream_batch_id": build_batch_id(
                    producer=period.raw_asset,
                    scope=context.partition_key,
                    payload={
                        "producer_run_id": context.run.run_id,
                        "frequency": period.frequency,
                        "period_end": result.period_end.isoformat(),
                    },
                ),
            },
        ),
        check_results=[
            index_period_raw_check_result(
                period,
                result.check,
                path=result.path,
                partition_key=context.partition_key,
                period_end=result.period_end,
            )
        ],
    )


@dg.asset(
    group_name="index",
    partitions_def=cn_a_index_week_ends,
    config_schema={},
    deps=["silver_trade_calendar"],
    required_resource_keys={"lake_root", "duckdb"},
    pool=INDEX_WEEKLY.raw_pool,
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id=INDEX_WEEKLY.dataset_id,
        source_system=SourceSystem.TUSHARE,
        data_contract=INDEX_WEEKLY.raw_contract,
        column_schema=RAW_INDEX_WEEKLY_SCHEMA,
        path_template=lake_path_template(
            raw_index_weekly_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
        source_api=INDEX_WEEKLY.dataset_id,
        source_doc=INDEX_WEEKLY.source_doc,
    ),
    check_specs=[index_period_raw_check_spec(INDEX_WEEKLY)],
    description="主要指数周线原始行情，按周管理。",
)
def raw_index_weekly(context: dg.AssetExecutionContext):
    yield from _update_raw_index_period(context, INDEX_WEEKLY)


@dg.asset(
    group_name="index",
    partitions_def=cn_a_index_months,
    config_schema={},
    deps=["silver_trade_calendar"],
    required_resource_keys={"lake_root", "duckdb"},
    pool=INDEX_MONTHLY.raw_pool,
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id=INDEX_MONTHLY.dataset_id,
        source_system=SourceSystem.TUSHARE,
        data_contract=INDEX_MONTHLY.raw_contract,
        column_schema=RAW_INDEX_WEEKLY_SCHEMA,
        path_template=lake_path_template(
            raw_index_monthly_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
        source_api=INDEX_MONTHLY.dataset_id,
        source_doc=INDEX_MONTHLY.source_doc,
    ),
    check_specs=[index_period_raw_check_spec(INDEX_MONTHLY)],
    description="主要指数月线原始行情，按月管理。",
)
def raw_index_monthly(context: dg.AssetExecutionContext):
    yield from _update_raw_index_period(context, INDEX_MONTHLY)


def _update_silver_index_period(context, config, period):
    context.resources.lake_root.ensure_available_for_run()
    if config.mode == "period":
        status = partition_dataset_readiness_status_from_latest_checks(
            context.instance,
            (AssetReadinessSpec(dg.AssetKey(period.raw_asset), (period.raw_check,)),),
            partition_key=context.partition_key,
        )
        if not status.ready:
            raise dg.Failure("期末Raw的本次物化及关联检查尚未通过")
    context.log.info(
        "开始更新%s，模式%s，分区%s",
        period.silver_asset,
        config.mode,
        context.partition_key,
    )
    try:
        with context.resources.duckdb.connect() as connection:
            result = write_index_period_silver(
                connection,
                lake_root=context.resources.lake_root.root(),
                period=period,
                partition_key=context.partition_key,
                run_id=context.run.run_id,
                config=config,
                staging_root=Path(DEFAULT_LAKE_STAGING_ROOT),
            )
    except IndexPeriodContractError as error:
        yield index_period_silver_check_result(
            period,
            error.result,
            path=index_period_candidate_path(
                Path(DEFAULT_LAKE_STAGING_ROOT),
                context.run.run_id,
                "silver",
                period.dataset_id,
            ),
            partition_key=context.partition_key,
            period_end=error.period_end,
        )
        raise dg.Failure(str(error)) from error
    yield dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=result.path,
            row_count=result.partition_row_count,
            observed_columns=[c.name for c in SILVER_INDEX_WEEKLY_SCHEMA],
            extra_metadata={
                "partition_key": context.partition_key,
                "trade_date": result.period_end.isoformat(),
                "frequency": period.frequency,
                "mode": config.mode,
                "source_assets": list(result.source_assets),
                "source_row_count": result.input_row_count,
                "changed_row_count": result.check.source_row_count,
                "file_row_count": result.check.file_row_count,
                **(
                    {
                        "daily_input": {
                            **result.daily_input,
                            "path_template": lake_path_template(
                                silver_index_daily_path(
                                    PATH_TEMPLATE_LAKE_ROOT, "{partition_key}"
                                )
                            ),
                        }
                    }
                    if result.daily_input
                    else {}
                ),
            },
        ),
        check_results=[
            index_period_silver_check_result(
                period,
                result.check,
                path=result.path,
                partition_key=context.partition_key,
                period_end=result.period_end,
            )
        ],
    )


@dg.asset(
    group_name="index",
    partitions_def=cn_a_index_week_ends,
    deps=[
        "silver_index_daily",
        "raw_index_weekly",
        "silver_trade_calendar",
        "silver_index_basic",
    ],
    required_resource_keys={"lake_root", "duckdb"},
    pool=INDEX_WEEKLY.silver_pool,
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id=INDEX_WEEKLY.dataset_id,
        source_system=SourceSystem.DERIVED,
        data_contract=INDEX_WEEKLY.silver_contract,
        column_schema=SILVER_INDEX_WEEKLY_SCHEMA,
        path_template=lake_path_template(
            silver_index_weekly_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
    ),
    check_specs=[index_period_silver_check_spec(INDEX_WEEKLY)],
    description="主要指数周线，按周管理并每日更新当期行情。",
)
def silver_index_weekly(
    context: dg.AssetExecutionContext, config: IndexPeriodSilverConfig
):
    yield from _update_silver_index_period(context, config, INDEX_WEEKLY)


@dg.asset(
    group_name="index",
    partitions_def=cn_a_index_months,
    deps=[
        "silver_index_daily",
        "raw_index_monthly",
        "silver_trade_calendar",
        "silver_index_basic",
    ],
    required_resource_keys={"lake_root", "duckdb"},
    pool=INDEX_MONTHLY.silver_pool,
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id=INDEX_MONTHLY.dataset_id,
        source_system=SourceSystem.DERIVED,
        data_contract=INDEX_MONTHLY.silver_contract,
        column_schema=SILVER_INDEX_WEEKLY_SCHEMA,
        path_template=lake_path_template(
            silver_index_monthly_path(PATH_TEMPLATE_LAKE_ROOT)
        ),
    ),
    check_specs=[index_period_silver_check_spec(INDEX_MONTHLY)],
    description="主要指数月线，按月管理并每日更新当期行情。",
)
def silver_index_monthly(
    context: dg.AssetExecutionContext, config: IndexPeriodSilverConfig
):
    yield from _update_silver_index_period(context, config, INDEX_MONTHLY)
