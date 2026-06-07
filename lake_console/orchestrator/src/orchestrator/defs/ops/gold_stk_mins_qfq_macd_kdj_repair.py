from datetime import date

import dagster as dg

from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_QFQ_FREQS,
    normalize_stk_mins_qfq_freq,
)
from orchestrator.defs.stk_mins_qfq import GOLD_STK_MINS_QFQ_WRITER_POOL
from orchestrator.defs.stk_mins_qfq_macd_kdj import (
    discover_gold_stk_mins_qfq_source_year_paths,
    discover_latest_macd_kdj_state_path_before_trade_date,
    write_gold_stk_mins_qfq_macd_kdj_rows,
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
        is_required=False,
        default_value=[],
        description="可选股票代码白名单；为空表示全市场。",
    ),
    "reason": dg.Field(
        str,
        is_required=False,
        default_value="manual_repair",
        description="repair 原因，仅写入日志。",
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
                for stock_code in context.op_config.get("stock_codes", [])
                if str(stock_code).strip()
            }
        )
    )
    reason = str(context.op_config.get("reason", "manual_repair")).strip()
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
