from datetime import date, datetime
from pathlib import Path

import dagster as dg

from orchestrator.defs.asset_guards.stk_mins_continuity import (
    assert_exact_previous_state_path,
    assert_expected_dates_registered,
    expected_trade_dates_between,
    is_first_expected_trade_date,
    load_stock_mins_expected_trade_dates,
    previous_expected_trade_date,
)
from orchestrator.defs.asset_guards.stk_mins_qfq_factor_repair import (
    GoldStkMinsQfqFactorRepairStatus,
    gold_stk_mins_qfq_factor_repair_status,
)
from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from orchestrator.defs.run_contracts.stk_mins import (
    STK_MINS_MACD_KDJ_BASELINE_START_DATE,
    STK_MINS_QFQ_FREQS,
    normalize_stk_mins_qfq_freq,
)
from orchestrator.defs.stk_mins_qfq import (
    GOLD_STK_MINS_QFQ_WRITER_POOL,
    QFQ_FACTOR_REPAIR_AUTO_MACD_KDJ_CODE_LIMIT,
)
from orchestrator.defs.stk_mins_qfq_macd_kdj import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME,
    discover_gold_stk_mins_qfq_source_year_paths,
    write_gold_stk_mins_qfq_macd_kdj_rows,
)
from orchestrator.utils.dg_log_helper import DgStdoutLogger


MACD_KDJ_REPAIR_EMPTY_STOCK_CODES_ERROR = (
    "MACD/KDJ repair requires explicit stock_codes; empty stock_codes would "
    "trigger full-market repair and is forbidden."
)
MACD_KDJ_REPAIR_MANUAL_UNSUPPORTED_ERROR = (
    "MACD/KDJ manual repair is unsupported without a qfq factor repair upstream batch."
)
LOGGER = DgStdoutLogger("stk_mins_qfq_macd_kdj_repair")


GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_CONFIG_SCHEMA = {
    "start_trade_date": dg.Field(
        str,
        is_required=False,
        default_value="",
        description="MACD/KDJ repair 起始交易日，格式 YYYY-MM-DD。",
    ),
    "qfq_factor_repair_trade_date": dg.Field(
        str,
        is_required=False,
        default_value="",
        description="可选 qfq factor repair 目标交易日；填写后自动读取该日期 repair metadata 生成 scoped repair config。",
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
        description="股票代码白名单；必须与 qfq factor repair metadata 完全一致，禁止空列表触发全市场 repair。",
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
    "upstream_batch_id": dg.Field(
        str,
        is_required=False,
        default_value="",
        description="来自 qfq factor repair metadata 的正式上游批次身份。",
    ),
}


def _normalize_trade_date(raw_trade_date: str) -> str:
    trade_date = _normalize_optional_trade_date(
        raw_trade_date,
        field_name="start_trade_date",
    )
    if trade_date is None:
        raise ValueError("start_trade_date must use YYYY-MM-DD format.")
    return trade_date


def _normalize_optional_trade_date(
    raw_trade_date: object,
    *,
    field_name: str,
) -> str | None:
    trade_date = str(raw_trade_date or "").strip()
    if not trade_date:
        return None
    try:
        return date.fromisoformat(trade_date).isoformat()
    except ValueError as error:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format.") from error


def _normalize_stock_codes(raw_stock_codes: object) -> tuple[str, ...]:
    if raw_stock_codes is None:
        return ()
    return tuple(
        sorted(
            {
                str(stock_code).strip()
                for stock_code in raw_stock_codes
                if str(stock_code).strip()
            }
        )
    )


def _load_macd_kdj_repair_expected_trade_dates(
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


def _repair_scope_from_qfq_factor_repair_status(
    status: GoldStkMinsQfqFactorRepairStatus,
) -> tuple[str, str, tuple[str, ...], str, str]:
    if not status.ready:
        raise dg.Failure(
            "MACD/KDJ repair could not read ready qfq factor repair metadata: "
            f"trade_date={status.trade_date}, reason={status.reason}."
        )
    if not status.rewrote_history:
        raise dg.Failure(
            "MACD/KDJ repair is not required for qfq factor repair trade_date: "
            f"trade_date={status.trade_date}, reason={status.reason}."
        )
    if not _automatic_macd_kdj_repair_allowed(status):
        raise dg.Failure(
            "MACD/KDJ repair cannot derive scoped stock_codes from qfq factor repair "
            "metadata: affected codes exceed the automatic limit or metadata is "
            f"incomplete, trade_date={status.trade_date}, "
            f"repair_required_code_count={status.repair_required_code_count}, "
            f"repair_required_codes_truncated={status.repair_required_codes_truncated}."
        )
    if status.repair_start_trade_date is None:
        raise dg.Failure(
            "MACD/KDJ repair qfq factor repair metadata is missing repair_start_trade_date: "
            f"trade_date={status.trade_date}."
        )
    if status.repair_end_trade_date is None:
        raise dg.Failure(
            "MACD/KDJ repair qfq factor repair metadata is missing repair_end_trade_date: "
            f"trade_date={status.trade_date}."
        )
    if status.repair_required_codes_hash is None:
        raise dg.Failure(
            "MACD/KDJ repair qfq factor repair metadata is missing repair_required_codes_hash: "
            f"trade_date={status.trade_date}."
        )
    if status.upstream_batch_id is None:
        raise dg.Failure(
            "MACD/KDJ repair qfq factor repair metadata is missing upstream_batch_id: "
            f"trade_date={status.trade_date}."
        )
    return (
        status.repair_start_trade_date,
        status.repair_end_trade_date,
        status.repair_required_codes,
        status.repair_required_codes_hash,
        status.upstream_batch_id,
    )


def _automatic_macd_kdj_repair_allowed(
    status: GoldStkMinsQfqFactorRepairStatus,
) -> bool:
    return (
        status.rewrote_history
        and 0
        < status.repair_required_code_count
        <= QFQ_FACTOR_REPAIR_AUTO_MACD_KDJ_CODE_LIMIT
        and not status.repair_required_codes_truncated
        and len(status.repair_required_codes) == status.repair_required_code_count
        and status.repair_required_codes_hash is not None
    )


def _assert_explicit_scope_matches_qfq_metadata(
    *,
    explicit_start_trade_date: str | None,
    explicit_stock_codes: tuple[str, ...],
    explicit_repair_required_codes_hash: str,
    explicit_upstream_batch_id: str,
    derived_start_trade_date: str,
    derived_stock_codes: tuple[str, ...],
    derived_repair_required_codes_hash: str,
    derived_upstream_batch_id: str,
    qfq_factor_repair_trade_date: str,
) -> None:
    if explicit_start_trade_date != derived_start_trade_date:
        raise dg.Failure(
            "MACD/KDJ repair start_trade_date does not match qfq factor repair metadata: "
            f"qfq_factor_repair_trade_date={qfq_factor_repair_trade_date}, "
            f"start_trade_date={explicit_start_trade_date}, "
            f"expected_start_trade_date={derived_start_trade_date}."
        )
    if explicit_stock_codes != derived_stock_codes:
        raise dg.Failure(
            "MACD/KDJ repair stock_codes do not match qfq factor repair metadata: "
            f"qfq_factor_repair_trade_date={qfq_factor_repair_trade_date}, "
            f"stock_code_count={len(explicit_stock_codes)}, "
            f"expected_stock_code_count={len(derived_stock_codes)}."
        )
    if explicit_repair_required_codes_hash != derived_repair_required_codes_hash:
        raise dg.Failure(
            "MACD/KDJ repair repair_required_codes_hash does not match qfq factor repair "
            f"metadata: qfq_factor_repair_trade_date={qfq_factor_repair_trade_date}."
        )
    if explicit_upstream_batch_id != derived_upstream_batch_id:
        raise dg.Failure(
            "MACD/KDJ repair upstream_batch_id does not match "
            "qfq factor repair metadata: "
            f"qfq_factor_repair_trade_date={qfq_factor_repair_trade_date}."
        )


def _repair_completion_human_metadata(
    *,
    start_trade_date: str,
    end_trade_date: str,
    freq_count: int,
    target_date_count: int,
    stock_code_count: int,
    repair_required_codes_hash: str,
    upstream_batch_id: str,
    qfq_factor_repair_trade_date: str,
    indicator_file_count: int,
    indicator_row_count: int,
    state_file_count: int,
    state_row_count: int,
) -> dict[str, object]:
    return {
        "summary": (
            "已完成 MACD/KDJ scoped repair，覆盖 "
            f"{start_trade_date} 至 {end_trade_date} 的 {target_date_count} 个交易日。"
        ),
        "next_action": (
            "等待 MACD/KDJ repair completed check 可见；若后续日常链路仍阻断，"
            "先看本批次 completion metadata 和 run stdout。"
        ),
        "result_status": "repair_completed",
        "input_summary": {
            "source_asset": "gold_stk_mins_qfq",
            "trigger_source": "qfq_factor_repair",
            "qfq_factor_repair_trade_date": qfq_factor_repair_trade_date,
            "upstream_batch_id": upstream_batch_id,
            "repair_required_codes_hash": repair_required_codes_hash,
        },
        "filter_summary": {
            "freq_count": freq_count,
            "target_date_count": target_date_count,
            "stock_code_count": stock_code_count,
            "indicator_file_count": indicator_file_count,
            "indicator_row_count": indicator_row_count,
            "state_file_count": state_file_count,
            "state_row_count": state_row_count,
        },
        "diagnostic_ref": (
            "完整执行范围看本条 check metadata 的 covered_*、code hash、upstream batch "
            "和 run stdout；stdout 不打印股票代码列表。"
        ),
    }


@dg.op(
    required_resource_keys={"lake_root", "duckdb"},
    config_schema=GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_CONFIG_SCHEMA,
    pool=GOLD_STK_MINS_QFQ_WRITER_POOL,
)
def gold_stk_mins_qfq_macd_kdj_repair_op(context: dg.OpExecutionContext) -> None:
    qfq_factor_repair_trade_date = _normalize_optional_trade_date(
        context.op_config.get("qfq_factor_repair_trade_date", ""),
        field_name="qfq_factor_repair_trade_date",
    )
    start_trade_date = _normalize_optional_trade_date(
        context.op_config.get("start_trade_date", ""),
        field_name="start_trade_date",
    )
    freqs = tuple(
        normalize_stk_mins_qfq_freq(freq) for freq in context.op_config.get("freqs", [])
    )
    stock_codes = _normalize_stock_codes(context.op_config.get("stock_codes", []))
    reason = str(context.op_config.get("reason", "manual_repair")).strip()
    repair_required_codes_hash = str(
        context.op_config.get("repair_required_codes_hash", "")
    ).strip()
    upstream_batch_id = str(context.op_config.get("upstream_batch_id", "")).strip()
    if qfq_factor_repair_trade_date is None or not upstream_batch_id:
        raise dg.Failure(MACD_KDJ_REPAIR_MANUAL_UNSUPPORTED_ERROR)
    if start_trade_date is None:
        raise dg.Failure("MACD/KDJ repair requires explicit start_trade_date.")
    if not stock_codes:
        raise dg.Failure(MACD_KDJ_REPAIR_EMPTY_STOCK_CODES_ERROR)
    if not repair_required_codes_hash:
        raise dg.Failure(
            "MACD/KDJ repair requires explicit repair_required_codes_hash."
        )

    qfq_factor_repair_status = gold_stk_mins_qfq_factor_repair_status(
        context.instance,
        qfq_factor_repair_trade_date,
    )
    (
        derived_start_trade_date,
        derived_end_trade_date,
        derived_stock_codes,
        derived_repair_required_codes_hash,
        derived_upstream_batch_id,
    ) = _repair_scope_from_qfq_factor_repair_status(qfq_factor_repair_status)
    _assert_explicit_scope_matches_qfq_metadata(
        explicit_start_trade_date=start_trade_date,
        explicit_stock_codes=stock_codes,
        explicit_repair_required_codes_hash=repair_required_codes_hash,
        explicit_upstream_batch_id=upstream_batch_id,
        derived_start_trade_date=derived_start_trade_date,
        derived_stock_codes=derived_stock_codes,
        derived_repair_required_codes_hash=derived_repair_required_codes_hash,
        derived_upstream_batch_id=derived_upstream_batch_id,
        qfq_factor_repair_trade_date=qfq_factor_repair_trade_date,
    )
    if not reason or reason == "manual_repair":
        reason = f"qfq_factor_repair:{qfq_factor_repair_trade_date}"

    lake_root = context.resources.lake_root.root()
    expected_trade_dates = _load_macd_kdj_repair_expected_trade_dates(
        lake_root=lake_root,
        duckdb_resource=context.resources.duckdb,
    )
    expected_trade_date_set = set(expected_trade_dates)
    if start_trade_date not in expected_trade_date_set:
        raise dg.Failure(
            description=(
                "MACD/KDJ repair start_trade_date is not an expected stock minutes "
                f"trade date: start_trade_date={start_trade_date}."
            ),
            metadata={"start_trade_date": start_trade_date},
        )
    if derived_end_trade_date not in expected_trade_date_set:
        raise dg.Failure(
            description=(
                "MACD/KDJ repair end_trade_date is not an expected stock minutes "
                f"trade date: end_trade_date={derived_end_trade_date}."
            ),
            metadata={"end_trade_date": derived_end_trade_date},
        )
    target_dates = expected_trade_dates_between(
        expected_trade_dates,
        start_trade_date=start_trade_date,
        end_trade_date=derived_end_trade_date,
    )

    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_mins_silver_trade_days.name
            )
        )
    )
    registered_target_dates = assert_expected_dates_registered(
        expected_trade_dates=expected_trade_dates,
        registered_trade_days=registered_trade_days,
        partition_set_name=cn_a_stock_mins_silver_trade_days.name,
        start_trade_date=start_trade_date,
        end_trade_date=derived_end_trade_date,
    )
    if registered_target_dates != target_dates:
        raise dg.Failure(
            description=(
                "MACD/KDJ repair expected range and registered range mismatch: "
                f"start_trade_date={start_trade_date}, "
                f"end_trade_date={derived_end_trade_date}."
            ),
            metadata={
                "start_trade_date": start_trade_date,
                "end_trade_date": derived_end_trade_date,
                "target_dates": list(target_dates),
                "registered_target_dates": list(registered_target_dates),
            },
        )
    previous_trade_date = previous_expected_trade_date(
        expected_trade_dates,
        start_trade_date,
    )
    allow_without_previous_state = (
        previous_trade_date is None
        and is_first_expected_trade_date(expected_trade_dates, start_trade_date)
    )
    LOGGER.stdout(
        "gold_stk_mins_qfq_macd_kdj_repair_started",
        qfq_factor_repair_trade_date=qfq_factor_repair_trade_date,
        start_trade_date=start_trade_date,
        end_trade_date=derived_end_trade_date,
        target_date_count=len(target_dates),
        freq_count=len(freqs),
        stock_code_count=len(stock_codes),
        repair_required_codes_hash=repair_required_codes_hash,
        upstream_batch_id=upstream_batch_id,
    )

    source_paths_by_freq: dict[int, tuple[Path, ...]] = {}
    previous_state_path_by_freq: dict[int, Path | None] = {}
    for freq in freqs:
        source_paths = discover_gold_stk_mins_qfq_source_year_paths(
            lake_root,
            freq=freq,
            trade_dates=target_dates,
        )
        if not source_paths:
            raise FileNotFoundError(
                "Missing source gold qfq files for MACD/KDJ repair: "
                f"freq={freq}, start_trade_date={start_trade_date}, "
                f"end_trade_date={derived_end_trade_date}."
            )
        previous_state_path = assert_exact_previous_state_path(
            lake_root=lake_root,
            freq=freq,
            target_trade_date=start_trade_date,
            previous_expected_trade_date=previous_trade_date,
            allow_without_previous_state=allow_without_previous_state,
        )
        source_paths_by_freq[freq] = source_paths
        previous_state_path_by_freq[freq] = previous_state_path

    total_indicator_file_count = 0
    total_indicator_row_count = 0
    total_state_file_count = 0
    total_state_row_count = 0
    for freq in freqs:
        source_paths = source_paths_by_freq[freq]
        previous_state_path = previous_state_path_by_freq[freq]
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
    LOGGER.stdout(
        "gold_stk_mins_qfq_macd_kdj_repair_completed",
        qfq_factor_repair_trade_date=qfq_factor_repair_trade_date,
        start_trade_date=start_trade_date,
        end_trade_date=target_dates[-1],
        target_date_count=len(target_dates),
        freq_count=len(freqs),
        stock_code_count=len(stock_codes),
        repair_required_codes_hash=repair_required_codes_hash,
        upstream_batch_id=upstream_batch_id,
        indicator_file_count=total_indicator_file_count,
        indicator_row_count=total_indicator_row_count,
        state_file_count=total_state_file_count,
        state_row_count=total_state_row_count,
    )
    completion_metadata = build_check_metadata(
        check_scope=CheckScope.RECONCILIATION,
        checked_row_count=total_indicator_row_count + total_state_row_count,
        failed_row_count=0,
        extra_metadata={
            **_repair_completion_human_metadata(
                start_trade_date=start_trade_date,
                end_trade_date=target_dates[-1],
                freq_count=len(freqs),
                target_date_count=len(target_dates),
                stock_code_count=len(stock_codes),
                repair_required_codes_hash=repair_required_codes_hash,
                upstream_batch_id=upstream_batch_id,
                qfq_factor_repair_trade_date=qfq_factor_repair_trade_date or "",
                indicator_file_count=total_indicator_file_count,
                indicator_row_count=total_indicator_row_count,
                state_file_count=total_state_file_count,
                state_row_count=total_state_row_count,
            ),
            "covered_start_trade_date": start_trade_date,
            "covered_end_trade_date": target_dates[-1],
            "freqs": list(freqs),
            "qfq_factor_repair_trade_date": qfq_factor_repair_trade_date or "",
            "stock_code_scope": "explicit",
            "stock_code_count": len(stock_codes),
            "repair_required_code_count": len(stock_codes),
            "repair_required_codes_hash": repair_required_codes_hash,
            "source_upstream_batch_id": upstream_batch_id,
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
