from collections.abc import Iterator

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_qfq_macd_kdj import (
    assert_gold_stk_mins_qfq_macd_kdj_daily_repair_gate,
)
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    PATH_TEMPLATE_TS_CODE,
    PATH_TEMPLATE_YEAR,
    gold_stk_mins_qfq_macd_kdj_path,
    gold_stk_mins_qfq_macd_kdj_state_path,
    lake_path_template,
)
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA,
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import AssetLayer, DataDomain, build_asset_tags
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.stk_mins_qfq import GOLD_STK_MINS_QFQ_WRITER_POOL
from orchestrator.defs.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_INDICATOR_VERSION,
    GOLD_STK_MINS_QFQ_MACD_KDJ_PARAMS_KEY,
    write_gold_stk_mins_qfq_macd_kdj_asset_partition,
)


def _indicator_asset_name(freq: int) -> str:
    return f"gold_stk_mins_qfq_macd_kdj_{freq}m"


def _state_asset_name(freq: int) -> str:
    return f"gold_stk_mins_qfq_macd_kdj_state_{freq}m"


def _indicator_definition_metadata(freq: int) -> dict:
    return build_asset_definition_metadata(
        dataset_id="stk_mins_qfq_macd_kdj",
        source_system=SourceSystem.DERIVED,
        data_contract="qfq_stock_minute_macd_kdj_indicators",
        column_schema=GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA,
        path_template=lake_path_template(
            gold_stk_mins_qfq_macd_kdj_path(
                PATH_TEMPLATE_LAKE_ROOT,
                freq,
                PATH_TEMPLATE_TS_CODE,
                PATH_TEMPLATE_YEAR,
            )
        ),
        extra_metadata={
            "freq": freq,
            "params_key": GOLD_STK_MINS_QFQ_MACD_KDJ_PARAMS_KEY,
            "indicator_version": GOLD_STK_MINS_QFQ_MACD_KDJ_INDICATOR_VERSION,
        },
    )


def _state_definition_metadata(freq: int) -> dict:
    return build_asset_definition_metadata(
        dataset_id="stk_mins_qfq_macd_kdj_state",
        source_system=SourceSystem.DERIVED,
        data_contract="qfq_stock_minute_macd_kdj_indicator_state",
        column_schema=GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA,
        path_template=lake_path_template(
            gold_stk_mins_qfq_macd_kdj_state_path(
                PATH_TEMPLATE_LAKE_ROOT,
                freq,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        extra_metadata={
            "freq": freq,
            "params_key": GOLD_STK_MINS_QFQ_MACD_KDJ_PARAMS_KEY,
            "indicator_version": GOLD_STK_MINS_QFQ_MACD_KDJ_INDICATOR_VERSION,
        },
    )


def _build_gold_stk_mins_qfq_macd_kdj_assets(freq: int) -> dg.AssetsDefinition:
    indicator_asset_name = _indicator_asset_name(freq)
    state_asset_name = _state_asset_name(freq)

    @dg.multi_asset(
        name=f"gold_stk_mins_qfq_macd_kdj_{freq}m_assets",
        specs=[
            dg.AssetSpec(
                indicator_asset_name,
                deps=[dg.AssetKey(f"gold_stk_mins_qfq_{freq}m")],
                partitions_def=cn_a_stock_mins_silver_trade_days,
                group_name="quote",
                tags=build_asset_tags(
                    layer=AssetLayer.GOLD,
                    data_domain=DataDomain.QUOTE_DATA,
                ),
                metadata=_indicator_definition_metadata(freq),
                description=(
                    f"股票 {freq} 分钟 qfq MACD/KDJ 指标，"
                    "从同频度 gold qfq 分钟线派生。"
                ),
            ),
            dg.AssetSpec(
                state_asset_name,
                deps=[dg.AssetKey(f"gold_stk_mins_qfq_{freq}m")],
                partitions_def=cn_a_stock_mins_silver_trade_days,
                group_name="quote",
                tags=build_asset_tags(
                    layer=AssetLayer.GOLD,
                    data_domain=DataDomain.QUOTE_DATA,
                ),
                metadata=_state_definition_metadata(freq),
                description=(
                    f"股票 {freq} 分钟 qfq MACD/KDJ 日终递推 state，"
                    "用于后续增量与 repair。"
                ),
            ),
        ],
        can_subset=False,
        pool=GOLD_STK_MINS_QFQ_WRITER_POOL,
    )
    def _assets(
        context: dg.AssetExecutionContext,
        lake_root: LakeRootResource,
    ) -> Iterator[dg.MaterializeResult]:
        lake_root.ensure_available_for_run()
        partition_key = context.partition_key
        assert_gold_stk_mins_qfq_macd_kdj_daily_repair_gate(
            context.instance,
            partition_key,
        )
        write_result = write_gold_stk_mins_qfq_macd_kdj_asset_partition(
            lake_root=lake_root.root(),
            freq=freq,
            partition_key=partition_key,
        )
        yield dg.MaterializeResult(
            asset_key=indicator_asset_name,
            metadata=build_materialization_metadata(
                uri=write_result.indicator_sample_file_paths[0],
                row_count=write_result.indicator_row_count,
                observed_columns=write_result.observed_indicator_columns,
                extra_metadata={
                    "freq": write_result.freq,
                    "partition_key": partition_key,
                    "source_file_count": write_result.source_file_count,
                    "output_file_count": write_result.indicator_file_count,
                    "output_sample_file_paths": list(
                        write_result.indicator_sample_file_paths
                    ),
                    "replacement_row_count": write_result.indicator_replacement_row_count,
                    "previous_state_file_path": (
                        str(write_result.previous_state_file_path)
                        if write_result.previous_state_file_path is not None
                        else None
                    ),
                    "initialized_without_previous_state": (
                        write_result.initialized_without_previous_state
                    ),
                },
            ),
        )
        yield dg.MaterializeResult(
            asset_key=state_asset_name,
            metadata=build_materialization_metadata(
                uri=write_result.state_file_path,
                row_count=write_result.state_row_count,
                observed_columns=write_result.observed_state_columns,
                extra_metadata={
                    "freq": write_result.freq,
                    "partition_key": partition_key,
                    "previous_state_file_path": (
                        str(write_result.previous_state_file_path)
                        if write_result.previous_state_file_path is not None
                        else None
                    ),
                    "initialized_without_previous_state": (
                        write_result.initialized_without_previous_state
                    ),
                },
            ),
        )

    return _assets


gold_stk_mins_qfq_macd_kdj_1m = _build_gold_stk_mins_qfq_macd_kdj_assets(1)
gold_stk_mins_qfq_macd_kdj_5m = _build_gold_stk_mins_qfq_macd_kdj_assets(5)
gold_stk_mins_qfq_macd_kdj_15m = _build_gold_stk_mins_qfq_macd_kdj_assets(15)
gold_stk_mins_qfq_macd_kdj_30m = _build_gold_stk_mins_qfq_macd_kdj_assets(30)
gold_stk_mins_qfq_macd_kdj_60m = _build_gold_stk_mins_qfq_macd_kdj_assets(60)
gold_stk_mins_qfq_macd_kdj_90m = _build_gold_stk_mins_qfq_macd_kdj_assets(90)
gold_stk_mins_qfq_macd_kdj_120m = _build_gold_stk_mins_qfq_macd_kdj_assets(120)

GOLD_STK_MINS_QFQ_MACD_KDJ_ASSETS = (
    gold_stk_mins_qfq_macd_kdj_1m,
    gold_stk_mins_qfq_macd_kdj_5m,
    gold_stk_mins_qfq_macd_kdj_15m,
    gold_stk_mins_qfq_macd_kdj_30m,
    gold_stk_mins_qfq_macd_kdj_60m,
    gold_stk_mins_qfq_macd_kdj_90m,
    gold_stk_mins_qfq_macd_kdj_120m,
)

GOLD_STK_MINS_QFQ_MACD_KDJ_ASSET_NAMES = tuple(
    _indicator_asset_name(freq) for freq in (1, 5, 15, 30, 60, 90, 120)
)
GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_ASSET_NAMES = tuple(
    _state_asset_name(freq) for freq in (1, 5, 15, 30, 60, 90, 120)
)
GOLD_STK_MINS_QFQ_MACD_KDJ_ALL_ASSET_NAMES = (
    GOLD_STK_MINS_QFQ_MACD_KDJ_ASSET_NAMES
    + GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_ASSET_NAMES
)
