"""QFQ daily and minute nine-turn Gold assets."""

from time import perf_counter

import dagster as dg

from orchestrator.defs.assets.stk_mins import (
    gold_stk_mins_qfq_30m,
    gold_stk_mins_qfq_60m,
    gold_stk_mins_qfq_90m,
    gold_stk_mins_qfq_120m,
)
from orchestrator.defs.assets.stock_daily_qfq import gold_stock_daily_qfq
from orchestrator.defs.partitions import (
    cn_a_stock_mins_silver_trade_days,
    cn_a_stock_trade_days,
)
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    gold_stk_mins_qfq_nineturn_path,
    gold_stock_daily_qfq_nineturn_path,
    lake_path_template,
)
from orchestrator.defs.qfq_nineturn import (
    build_gold_stk_mins_qfq_nineturn_partition_select_sql,
    build_gold_stock_daily_qfq_nineturn_partition_select_sql,
    plan_gold_stk_mins_qfq_nineturn_source,
    plan_gold_stock_daily_qfq_nineturn_source,
    write_gold_stk_mins_qfq_nineturn_partition,
    write_gold_stock_daily_qfq_nineturn_partition,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_NINETURN_SCHEMA,
    GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.run_contracts.qfq_nineturn import (
    QFQ_NINETURN_COMPARISON_LAG,
    QFQ_NINETURN_SIGNAL_THRESHOLD,
    QFQ_NINETURN_VERSION,
)
from orchestrator.defs.stk_mins_qfq import GOLD_STK_MINS_QFQ_WRITER_POOL
from orchestrator.utils.dg_log_helper import DgStdoutLogger


def _previous_registered_trade_date(
    context: dg.AssetExecutionContext,
    *,
    partition_set_name: str,
) -> str | None:
    partition_key = context.partition_key
    earlier_keys = sorted(
        key
        for key in context.instance.get_dynamic_partitions(partition_set_name)
        if key < partition_key
    )
    return earlier_keys[-1] if earlier_keys else None


def _materialization_metadata(result, *, partition_key: str, freq: int | None):
    asset_label = "日线" if freq is None else f"{freq} 分钟"
    return build_materialization_metadata(
        uri=result.target_path,
        row_count=result.output_row_count,
        observed_columns=result.observed_columns,
        extra_metadata={
            "summary": f"已生成股票{asset_label}前复权九转分区。",
            "next_action": "等待聚合完整性检查通过后供每日扫描和多周期研究消费。",
            "result_status": "written",
            "input_summary": {
                "partition_key": partition_key,
                "freq": freq if freq is not None else "daily",
                "source_file_count": result.source_file_count,
                "source_row_count": result.source_row_count,
            },
            "filter_summary": {
                "output_row_count": result.output_row_count,
                "stock_code_count": result.stock_code_count,
                "fallback_recomputed_code_count": (
                    result.fallback_recomputed_code_count
                ),
            },
            "diagnostic_ref": "完整诊断看对应 integrity check 和 run stdout。",
            "source_fingerprint": result.source_fingerprint,
            "source_row_count": result.source_row_count,
            "stock_code_count": result.stock_code_count,
            "fallback_recomputed_code_count": result.fallback_recomputed_code_count,
            "formula_version": QFQ_NINETURN_VERSION,
        },
    )


@dg.asset(
    name="gold_stock_daily_qfq_nineturn",
    deps=[
        dg.AssetDep(
            gold_stock_daily_qfq,
            partition_mapping=dg.IdentityPartitionMapping(),
        )
    ],
    partitions_def=cn_a_stock_trade_days,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.GOLD, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="stock_daily_qfq_nineturn",
        source_system=SourceSystem.DERIVED,
        data_contract="qfq_stock_daily_nineturn",
        column_schema=GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA,
        path_template=lake_path_template(
            gold_stock_daily_qfq_nineturn_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        extra_metadata={
            "formula_version": QFQ_NINETURN_VERSION,
            "comparison_lag": QFQ_NINETURN_COMPARISON_LAG,
            "signal_threshold": QFQ_NINETURN_SIGNAL_THRESHOLD,
            "calculation_model": "fixed_formula_non_repainting",
            "physical_layout": "trade_date_single_file",
        },
    ),
    description="股票日线前复权九转指标，按交易日保存全市场收盘价、连续计数和正负九信号，供每日扫描和多周期研究使用。",
)
def gold_stock_daily_qfq_nineturn(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    started_at = perf_counter()
    partition_key = context.partition_key
    root = lake_root.root()
    log = DgStdoutLogger("qfq_nineturn")
    log.stdout(
        "qfq_nineturn_started",
        asset="gold_stock_daily_qfq_nineturn",
        partition_key=partition_key,
        freq="daily",
    )
    try:
        previous_trade_date = _previous_registered_trade_date(
            context,
            partition_set_name=cn_a_stock_trade_days.name,
        )
        connect_duckdb = duckdb.connect
        with connect_duckdb() as connection:
            plan = plan_gold_stock_daily_qfq_nineturn_source(
                connection,
                lake_root=root,
                partition_key=partition_key,
                previous_trade_date=previous_trade_date,
            )
        log.stdout(
            "qfq_nineturn_source_loaded",
            asset="gold_stock_daily_qfq_nineturn",
            partition_key=partition_key,
            source_row_count=plan.source_row_count,
            fallback_code_count=len(plan.fallback_codes),
        )
        if plan.fallback_codes:
            log.stdout(
                "qfq_nineturn_fallback_started",
                asset="gold_stock_daily_qfq_nineturn",
                partition_key=partition_key,
                fallback_code_count=len(plan.fallback_codes),
            )
        select_sql = build_gold_stock_daily_qfq_nineturn_partition_select_sql(
            source_paths=plan.source_paths,
            target_trade_date=partition_key,
            previous_partition_path=plan.previous_partition_path,
            fallback_source_paths=plan.fallback_source_paths,
            fallback_codes=plan.fallback_codes,
        )
        result = write_gold_stock_daily_qfq_nineturn_partition(
            duckdb_resource=duckdb,
            lake_root=root,
            partition_key=partition_key,
            run_id=context.run_id,
            select_sql=select_sql,
            source_paths=plan.source_paths,
            fingerprint_source_paths=plan.fingerprint_source_paths,
            source_row_count=plan.source_row_count,
            fallback_recomputed_code_count=len(plan.fallback_codes),
        )
    except Exception:
        log.stdout(
            "qfq_nineturn_validation_failed",
            asset="gold_stock_daily_qfq_nineturn",
            partition_key=partition_key,
            freq="daily",
        )
        raise
    log.stdout(
        "qfq_nineturn_completed",
        asset="gold_stock_daily_qfq_nineturn",
        partition_key=partition_key,
        output_row_count=result.output_row_count,
        stock_code_count=result.stock_code_count,
        fallback_code_count=result.fallback_recomputed_code_count,
        elapsed_ms=round((perf_counter() - started_at) * 1000, 3),
    )
    return dg.MaterializeResult(
        metadata=_materialization_metadata(
            result,
            partition_key=partition_key,
            freq=None,
        )
    )


def _build_minute_asset(*, freq: int, source_asset):
    asset_name = f"gold_stk_mins_qfq_nineturn_{freq}m"

    @dg.asset(
        name=asset_name,
        deps=[
            dg.AssetDep(
                source_asset,
                partition_mapping=dg.IdentityPartitionMapping(),
            )
        ],
        partitions_def=cn_a_stock_mins_silver_trade_days,
        group_name="quote",
        tags=build_asset_tags(
            layer=AssetLayer.GOLD,
            data_domain=DataDomain.QUOTE_DATA,
        ),
        pool=GOLD_STK_MINS_QFQ_WRITER_POOL,
        metadata=build_asset_definition_metadata(
            dataset_id="stk_mins_qfq_nineturn",
            source_system=SourceSystem.DERIVED,
            data_contract="qfq_stock_minute_nineturn",
            column_schema=GOLD_STK_MINS_QFQ_NINETURN_SCHEMA,
            path_template=lake_path_template(
                gold_stk_mins_qfq_nineturn_path(
                    PATH_TEMPLATE_LAKE_ROOT,
                    freq,
                    PATH_TEMPLATE_PARTITION_KEY,
                )
            ),
            extra_metadata={
                "freq": freq,
                "formula_version": QFQ_NINETURN_VERSION,
                "comparison_lag": QFQ_NINETURN_COMPARISON_LAG,
                "signal_threshold": QFQ_NINETURN_SIGNAL_THRESHOLD,
                "calculation_model": "fixed_formula_non_repainting",
                "physical_layout": "freq_trade_date_single_file",
            },
        ),
        description=f"股票 {freq} 分钟前复权九转指标，按交易日保存业务键、连续计数和正负九信号，供多周期机会扫描使用。",
    )
    def _asset(
        context: dg.AssetExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.MaterializeResult:
        lake_root.ensure_available_for_run()
        started_at = perf_counter()
        partition_key = context.partition_key
        root = lake_root.root()
        log = DgStdoutLogger("qfq_nineturn")
        log.stdout(
            "qfq_nineturn_started",
            asset=asset_name,
            partition_key=partition_key,
            freq=freq,
        )
        try:
            previous_trade_date = _previous_registered_trade_date(
                context,
                partition_set_name=cn_a_stock_mins_silver_trade_days.name,
            )
            connect_duckdb = duckdb.connect
            with connect_duckdb() as connection:
                plan = plan_gold_stk_mins_qfq_nineturn_source(
                    connection,
                    lake_root=root,
                    freq=freq,
                    partition_key=partition_key,
                    previous_trade_date=previous_trade_date,
                )
            log.stdout(
                "qfq_nineturn_source_loaded",
                asset=asset_name,
                partition_key=partition_key,
                freq=freq,
                source_row_count=plan.source_row_count,
                fallback_code_count=len(plan.fallback_codes),
            )
            if plan.fallback_codes:
                log.stdout(
                    "qfq_nineturn_fallback_started",
                    asset=asset_name,
                    partition_key=partition_key,
                    freq=freq,
                    fallback_code_count=len(plan.fallback_codes),
                )
            select_sql = build_gold_stk_mins_qfq_nineturn_partition_select_sql(
                source_paths=plan.source_paths,
                freq=freq,
                target_trade_date=partition_key,
                previous_partition_path=plan.previous_partition_path,
                fallback_source_paths=plan.fallback_source_paths,
                fallback_codes=plan.fallback_codes,
            )
            result = write_gold_stk_mins_qfq_nineturn_partition(
                duckdb_resource=duckdb,
                lake_root=root,
                freq=freq,
                partition_key=partition_key,
                run_id=context.run_id,
                select_sql=select_sql,
                source_paths=plan.source_paths,
                fingerprint_source_paths=plan.fingerprint_source_paths,
                source_row_count=plan.source_row_count,
                fallback_recomputed_code_count=len(plan.fallback_codes),
            )
        except Exception:
            log.stdout(
                "qfq_nineturn_validation_failed",
                asset=asset_name,
                partition_key=partition_key,
                freq=freq,
            )
            raise
        log.stdout(
            "qfq_nineturn_completed",
            asset=asset_name,
            partition_key=partition_key,
            freq=freq,
            output_row_count=result.output_row_count,
            stock_code_count=result.stock_code_count,
            fallback_code_count=result.fallback_recomputed_code_count,
            elapsed_ms=round((perf_counter() - started_at) * 1000, 3),
        )
        return dg.MaterializeResult(
            metadata=_materialization_metadata(
                result,
                partition_key=partition_key,
                freq=freq,
            )
        )

    return _asset


gold_stk_mins_qfq_nineturn_30m = _build_minute_asset(
    freq=30,
    source_asset=gold_stk_mins_qfq_30m,
)
gold_stk_mins_qfq_nineturn_60m = _build_minute_asset(
    freq=60,
    source_asset=gold_stk_mins_qfq_60m,
)
gold_stk_mins_qfq_nineturn_90m = _build_minute_asset(
    freq=90,
    source_asset=gold_stk_mins_qfq_90m,
)
gold_stk_mins_qfq_nineturn_120m = _build_minute_asset(
    freq=120,
    source_asset=gold_stk_mins_qfq_120m,
)

GOLD_STK_MINS_QFQ_NINETURN_ASSETS = (
    gold_stk_mins_qfq_nineturn_30m,
    gold_stk_mins_qfq_nineturn_60m,
    gold_stk_mins_qfq_nineturn_90m,
    gold_stk_mins_qfq_nineturn_120m,
)
