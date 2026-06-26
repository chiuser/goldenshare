from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_continuity import (
    is_first_expected_trade_date,
    load_stock_mins_expected_trade_dates,
    previous_expected_trade_date,
)
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
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
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
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_MACD_KDJ_BASELINE_START_DATE,
)
from orchestrator.defs.stk_mins_qfq import GOLD_STK_MINS_QFQ_WRITER_POOL
from orchestrator.defs.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_INDICATOR_VERSION,
    GOLD_STK_MINS_QFQ_MACD_KDJ_PARAMS_KEY,
    GoldStkMinsQfqMacdKdjPartitionWriteResult,
    write_gold_stk_mins_qfq_macd_kdj_asset_partition,
)
from orchestrator.utils.dg_log_helper import DgStdoutLogger


LOGGER = DgStdoutLogger("stk_mins_qfq_macd_kdj")


def _load_macd_kdj_expected_trade_dates(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
) -> tuple[str, ...]:
    calendar_path = silver_trade_calendar_path(lake_root)
    if not calendar_path.exists():
        raise FileNotFoundError(
            f"silver_trade_calendar file is missing: {calendar_path}"
        )
    with duckdb_resource.connect() as connection:
        return load_stock_mins_expected_trade_dates(
            connection,
            calendar_path,
            min_trade_date=STK_MINS_MACD_KDJ_BASELINE_START_DATE,
            evaluated_at=datetime.now(),
            same_day_register_start=None,
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


def _human_materialization_metadata(
    *,
    summary: str,
    next_action: str,
    result_status: str,
    input_summary: dict[str, Any],
    filter_summary: dict[str, Any],
    diagnostic_ref: str,
) -> dict[str, Any]:
    return {
        "goldenshare/summary": summary,
        "goldenshare/next_action": next_action,
        "goldenshare/result_status": result_status,
        "goldenshare/input_summary": input_summary,
        "goldenshare/filter_summary": filter_summary,
        "goldenshare/diagnostic_ref": diagnostic_ref,
    }


def _macd_kdj_indicator_human_metadata(
    *,
    write_result: GoldStkMinsQfqMacdKdjPartitionWriteResult,
    partition_key: str,
    previous_trade_date: str | None,
) -> dict[str, Any]:
    return _human_materialization_metadata(
        summary=(
            f"已写入股票 {write_result.freq}min 分钟 qfq MACD/KDJ 指标："
            f"交易日 {partition_key}，{write_result.indicator_row_count} 行，"
            f"{write_result.indicator_file_count} 个股票年份文件。"
        ),
        next_action=(
            "等待 MACD/KDJ indicator blocking checks 全部通过；通过后 state "
            "和后续指标消费方可以继续。"
        ),
        result_status="written",
        input_summary={
            "source_asset": f"gold_stk_mins_qfq_{write_result.freq}m",
            "state_asset": f"gold_stk_mins_qfq_macd_kdj_state_{write_result.freq}m",
            "source_file_count": write_result.source_file_count,
            "previous_trade_date": previous_trade_date,
            "previous_state_ready": write_result.previous_state_file_path is not None,
            "initialized_without_previous_state": (
                write_result.initialized_without_previous_state
            ),
        },
        filter_summary={
            "output_row_count": write_result.indicator_row_count,
            "output_file_count": write_result.indicator_file_count,
            "replacement_row_count": write_result.indicator_replacement_row_count,
            "physical_layout": "freq_ts_code_year",
            "params_key": GOLD_STK_MINS_QFQ_MACD_KDJ_PARAMS_KEY,
            "indicator_version": GOLD_STK_MINS_QFQ_MACD_KDJ_INDICATOR_VERSION,
        },
        diagnostic_ref=(
            "完整诊断看 MACD/KDJ indicator checks metadata 和本次 run stdout。"
        ),
    )


def _macd_kdj_state_human_metadata(
    *,
    write_result: GoldStkMinsQfqMacdKdjPartitionWriteResult,
    partition_key: str,
    previous_trade_date: str | None,
) -> dict[str, Any]:
    return _human_materialization_metadata(
        summary=(
            f"已写入股票 {write_result.freq}min 分钟 qfq MACD/KDJ 日终 state："
            f"交易日 {partition_key}，{write_result.state_row_count} 行。"
        ),
        next_action=(
            "等待 state blocking checks 全部通过；通过后下一 expected 交易日的 "
            "MACD/KDJ daily 可以承接该状态。"
        ),
        result_status="written",
        input_summary={
            "source_asset": f"gold_stk_mins_qfq_macd_kdj_{write_result.freq}m",
            "previous_trade_date": previous_trade_date,
            "previous_state_ready": write_result.previous_state_file_path is not None,
            "initialized_without_previous_state": (
                write_result.initialized_without_previous_state
            ),
        },
        filter_summary={
            "state_row_count": write_result.state_row_count,
            "source_file_count": write_result.source_file_count,
            "indicator_row_count": write_result.indicator_row_count,
            "params_key": GOLD_STK_MINS_QFQ_MACD_KDJ_PARAMS_KEY,
            "indicator_version": GOLD_STK_MINS_QFQ_MACD_KDJ_INDICATOR_VERSION,
        },
        diagnostic_ref="完整诊断看 MACD/KDJ state checks metadata 和本次 run stdout。",
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
        duckdb: DuckDBResource,
    ) -> Iterator[dg.MaterializeResult]:
        lake_root.ensure_available_for_run()
        lake_root_path = lake_root.root()
        partition_key = context.partition_key
        expected_trade_dates = _load_macd_kdj_expected_trade_dates(
            lake_root=lake_root_path,
            duckdb_resource=duckdb,
        )
        if partition_key not in expected_trade_dates:
            raise dg.Failure(
                description=(
                    "MACD/KDJ daily target is not an expected stock minutes "
                    f"trade date: partition_key={partition_key}."
                ),
                metadata={
                    "partition_key": partition_key,
                    "expected_start_date": (
                        expected_trade_dates[0] if expected_trade_dates else ""
                    ),
                    "expected_end_date": (
                        expected_trade_dates[-1] if expected_trade_dates else ""
                    ),
                },
            )
        previous_trade_date = previous_expected_trade_date(
            expected_trade_dates,
            partition_key,
        )
        allow_without_previous_state = (
            previous_trade_date is None
            and is_first_expected_trade_date(expected_trade_dates, partition_key)
        )
        assert_gold_stk_mins_qfq_macd_kdj_daily_repair_gate(
            context.instance,
            partition_key,
        )
        LOGGER.stdout(
            "gold_stk_mins_qfq_macd_kdj_started",
            partition_key=partition_key,
            freq=freq,
            previous_trade_date=previous_trade_date,
            allow_without_previous_state=allow_without_previous_state,
        )
        write_result = write_gold_stk_mins_qfq_macd_kdj_asset_partition(
            lake_root=lake_root_path,
            freq=freq,
            partition_key=partition_key,
            previous_expected_trade_date=previous_trade_date,
            allow_without_previous_state=allow_without_previous_state,
        )
        LOGGER.stdout(
            "gold_stk_mins_qfq_macd_kdj_indicator_completed",
            partition_key=partition_key,
            freq=write_result.freq,
            source_file_count=write_result.source_file_count,
            output_file_count=write_result.indicator_file_count,
            output_row_count=write_result.indicator_row_count,
            replacement_row_count=write_result.indicator_replacement_row_count,
        )
        LOGGER.stdout(
            "gold_stk_mins_qfq_macd_kdj_state_completed",
            partition_key=partition_key,
            freq=write_result.freq,
            state_row_count=write_result.state_row_count,
            previous_state_ready=write_result.previous_state_file_path is not None,
            initialized_without_previous_state=(
                write_result.initialized_without_previous_state
            ),
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
                    **_macd_kdj_indicator_human_metadata(
                        write_result=write_result,
                        partition_key=partition_key,
                        previous_trade_date=previous_trade_date,
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
                    **_macd_kdj_state_human_metadata(
                        write_result=write_result,
                        partition_key=partition_key,
                        previous_trade_date=previous_trade_date,
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
