from datetime import date

import dagster as dg

from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_QFQ_FREQS,
    normalize_stk_mins_qfq_freq,
)
from orchestrator.defs.stk_mins_qfq import GOLD_STK_MINS_QFQ_WRITER_POOL
from orchestrator.defs.stk_mins_qfq import (
    gold_stk_mins_qfq_factor_repair_codes_hash,
)
from orchestrator.defs.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
    discover_gold_stk_mins_qfq_source_year_paths,
    discover_latest_macd_kdj_state_path_before_trade_date,
    write_gold_stk_mins_qfq_macd_kdj_rows,
)


M12_REPAIR_EMPTY_STOCK_CODES_ERROR = (
    "M12 repair requires explicit stock_codes; empty stock_codes would trigger "
    "full-market repair and is forbidden."
)


GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_CONFIG_SCHEMA = {
    "start_trade_date": dg.Field(
        str,
        description="MACD/KDJ repair 起始交易日，格式 YYYY-MM-DD。",
    ),
    "freqs": dg.Field(
        [int],
        is_required=False,
        default_value=list(STK_MINS_QFQ_FREQS),
        description="需要 repair 的分钟频度，允许 1/5/15/30/60/90/120。",
    ),
    "stock_codes": dg.Field(
        [str],
        is_required=True,
        description="必填股票代码白名单，trim/去重后不能为空；repair job 不提供全市场默认入口。",
    ),
    "reason": dg.Field(
        str,
        is_required=False,
        default_value="manual_repair",
        description="repair 原因，仅写入日志。",
    ),
    "repair_required_codes_hash": dg.Field(
        str,
        is_required=False,
        default_value="",
        description="来自 qfq factor repair affected codes 的稳定 SHA-256 hash。",
    ),
    "source_qfq_factor_repair_event_storage_ids": dg.Field(
        [int],
        is_required=False,
        default_value=[],
        description="触发本次 M12 repair 的 qfq factor repair check event storage id 列表。",
    ),
}


def _normalize_trade_date(raw_trade_date: str) -> str:
    try:
        return date.fromisoformat(str(raw_trade_date).strip()).isoformat()
    except ValueError as error:
        raise ValueError("start_trade_date must use YYYY-MM-DD format.") from error


def _target_trade_dates(
    registered_trade_days: tuple[str, ...],
    start_trade_date: str,
) -> tuple[str, ...]:
    target_dates = tuple(
        trade_date for trade_date in registered_trade_days if trade_date >= start_trade_date
    )
    if not target_dates:
        raise RuntimeError(
            "No registered trade days at or after MACD/KDJ repair start date: "
            f"start_trade_date={start_trade_date}."
        )
    return target_dates


def _repair_completion_asset_keys() -> tuple[dg.AssetKey, ...]:
    indicator_keys = tuple(
        dg.AssetKey(f"gold_stk_mins_qfq_macd_kdj_{freq}m")
        for freq in STK_MINS_QFQ_FREQS
    )
    state_keys = tuple(
        dg.AssetKey(f"gold_stk_mins_qfq_macd_kdj_state_{freq}m")
        for freq in STK_MINS_QFQ_FREQS
    )
    return indicator_keys + state_keys


@dg.op(
    required_resource_keys={"lake_root"},
    config_schema=GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_CONFIG_SCHEMA,
    pool=GOLD_STK_MINS_QFQ_WRITER_POOL,
)
def gold_stk_mins_qfq_macd_kdj_repair_op(context: dg.OpExecutionContext) -> None:
    start_trade_date = _normalize_trade_date(context.op_config["start_trade_date"])
    freqs = tuple(
        normalize_stk_mins_qfq_freq(freq) for freq in context.op_config.get("freqs", [])
    )
    stock_codes = tuple(
        sorted(
            {
                str(stock_code).strip()
                for stock_code in context.op_config["stock_codes"]
                if str(stock_code).strip()
            }
        )
    )
    if not stock_codes:
        raise dg.Failure(M12_REPAIR_EMPTY_STOCK_CODES_ERROR)
    reason = str(context.op_config.get("reason", "manual_repair")).strip()
    repair_required_codes_hash = str(
        context.op_config.get("repair_required_codes_hash", "")
    ).strip() or gold_stk_mins_qfq_factor_repair_codes_hash(stock_codes)
    source_qfq_factor_repair_event_storage_ids = tuple(
        sorted(
            int(event_storage_id)
            for event_storage_id in context.op_config.get(
                "source_qfq_factor_repair_event_storage_ids",
                [],
            )
        )
    )
    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name
            )
        )
    )
    target_dates = _target_trade_dates(registered_trade_days, start_trade_date)
    lake_root = context.resources.lake_root.root()

    total_indicator_file_count = 0
    total_indicator_row_count = 0
    total_state_file_count = 0
    total_state_row_count = 0
    for freq in freqs:
        source_paths = discover_gold_stk_mins_qfq_source_year_paths(
            lake_root,
            freq=freq,
            trade_dates=target_dates,
        )
        if not source_paths:
            raise FileNotFoundError(
                "Missing source gold qfq files for MACD/KDJ repair: "
                f"freq={freq}, start_trade_date={start_trade_date}."
            )
        previous_state_path = discover_latest_macd_kdj_state_path_before_trade_date(
            lake_root,
            freq=freq,
            trade_date=start_trade_date,
        )
        indicator_results, state_results, initialized_without_previous_state = (
            write_gold_stk_mins_qfq_macd_kdj_rows(
                lake_root=lake_root,
                freq=freq,
                source_qfq_paths=source_paths,
                target_trade_dates=target_dates,
                previous_state_paths=(
                    (previous_state_path,) if previous_state_path is not None else ()
                ),
                stock_codes=stock_codes,
            )
        )
        total_indicator_file_count += len(indicator_results)
        total_indicator_row_count += sum(
            result.replacement_row_count for result in indicator_results
        )
        total_state_file_count += len(state_results)
        total_state_row_count += sum(result.row_count for result in state_results)
        context.log.info(
            "Gold qfq MACD/KDJ repair batch completed: freq=%s start_trade_date=%s "
            "target_date_count=%s stock_code_count=%s source_file_count=%s "
            "indicator_file_count=%s state_file_count=%s initialized_without_previous_state=%s",
            freq,
            start_trade_date,
            len(target_dates),
            len(stock_codes),
            len(source_paths),
            len(indicator_results),
            len(state_results),
            initialized_without_previous_state,
        )

    context.log.info(
        "Gold qfq MACD/KDJ repair completed: reason=%s start_trade_date=%s "
        "freq_count=%s target_date_count=%s indicator_file_count=%s "
        "indicator_row_count=%s state_file_count=%s state_row_count=%s",
        reason,
        start_trade_date,
        len(freqs),
        len(target_dates),
        total_indicator_file_count,
        total_indicator_row_count,
        total_state_file_count,
        total_state_row_count,
    )
    completion_metadata = build_check_metadata(
        check_scope=CheckScope.RECONCILIATION,
        checked_row_count=total_indicator_row_count + total_state_row_count,
        failed_row_count=0,
        extra_metadata={
            "covered_start_trade_date": start_trade_date,
            "covered_end_trade_date": target_dates[-1],
            "freqs": list(freqs),
            "stock_code_scope": "explicit",
            "stock_code_count": len(stock_codes),
            "repair_required_code_count": len(stock_codes),
            "repair_required_codes_hash": repair_required_codes_hash,
            "source_qfq_factor_repair_event_storage_ids": list(
                source_qfq_factor_repair_event_storage_ids
            ),
            "reason": reason,
            "indicator_file_count": total_indicator_file_count,
            "indicator_row_count": total_indicator_row_count,
            "state_file_count": total_state_file_count,
            "state_row_count": total_state_row_count,
        },
    )
    for asset_key in _repair_completion_asset_keys():
        context.log_event(
            dg.AssetCheckEvaluation(
                asset_key=asset_key,
                check_name=GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
                passed=True,
                metadata=completion_metadata,
                blocking=True,
                partition=start_trade_date,
            )
        )
