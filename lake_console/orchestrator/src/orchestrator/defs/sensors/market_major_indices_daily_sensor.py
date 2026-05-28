from datetime import datetime

import dagster as dg

from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.sensors.market_major_indices_input_readiness import (
    MarketMajorIndicesInputReadiness,
    check_market_major_indices_inputs_for_trade_date,
)
from orchestrator.defs.sensors.readiness import (
    AssetReadinessStatus,
    CN_A_SENSOR_TIMEZONE,
    gold_market_major_indices_daily_ready_for_trade_date,
    silver_index_basic_ready,
    silver_index_daily_ready_for_trade_date,
)


MAX_STATUS_SAMPLE_COUNT = 20


def _asset_status_payload(status: AssetReadinessStatus | None) -> dict[str, object] | None:
    if status is None:
        return None
    return {
        "asset_key": status.asset_key,
        "partition_key": status.partition_key,
        "ready": status.ready,
        "materialized": status.materialized,
        "checks_passed": status.checks_passed,
        "freshness_passed": status.freshness_passed,
        "materialization_storage_id": status.materialization_storage_id,
        "materialization_date": status.materialization_date,
        "missing_check_names": list(status.missing_check_names),
        "failed_check_names": list(status.failed_check_names),
        "reason": status.reason,
    }


def _input_status_payload(
    status: MarketMajorIndicesInputReadiness | None,
) -> dict[str, object] | None:
    if status is None:
        return None
    return {
        "trade_date": status.trade_date,
        "ready": status.ready,
        "seed_row_count": status.seed_row_count,
        "active_seed_code_count": status.active_seed_code_count,
        "registered_code_count": status.registered_code_count,
        "missing_registered_seed_code_count": len(
            status.missing_registered_seed_codes
        ),
        "missing_index_basic_file": status.missing_index_basic_file,
        "missing_index_basic_seed_code_count": len(
            status.missing_index_basic_seed_codes
        ),
        "missing_silver_daily_file": status.missing_silver_daily_file,
        "missing_silver_daily_seed_code_count": len(
            status.missing_silver_daily_seed_codes
        ),
        "missing_registered_seed_code_samples": list(
            status.missing_registered_seed_codes[:MAX_STATUS_SAMPLE_COUNT]
        ),
        "missing_index_basic_seed_code_samples": list(
            status.missing_index_basic_seed_codes[:MAX_STATUS_SAMPLE_COUNT]
        ),
        "missing_silver_daily_seed_code_samples": list(
            status.missing_silver_daily_seed_codes[:MAX_STATUS_SAMPLE_COUNT]
        ),
        "scan_error_code": status.scan_error_code,
        "scan_error": status.scan_error,
    }


def _latest_registered_trade_date(
    registered_trade_days: tuple[str, ...],
    evaluated_at: datetime,
) -> str | None:
    today = evaluated_at.date().isoformat()
    eligible_trade_days = tuple(
        trade_date for trade_date in registered_trade_days if trade_date <= today
    )
    return eligible_trade_days[-1] if eligible_trade_days else None


def _input_sample_keys(
    input_status: MarketMajorIndicesInputReadiness | None,
) -> tuple[str, ...]:
    if input_status is None:
        return ()
    return (
        input_status.missing_registered_seed_codes
        or input_status.missing_index_basic_seed_codes
        or input_status.missing_silver_daily_seed_codes
    )[:MAX_STATUS_SAMPLE_COUNT]


def _blocked_count(
    *,
    selected_trade_date: str | None,
    blocked_fallback: int = 0,
    gold_status: AssetReadinessStatus | None = None,
    silver_status: AssetReadinessStatus | None = None,
    index_basic_status: AssetReadinessStatus | None = None,
    input_status: MarketMajorIndicesInputReadiness | None = None,
) -> int:
    if selected_trade_date:
        return 0
    if input_status is not None:
        return input_status.blocked_count
    if any(
        status is not None and not status.ready
        for status in (gold_status, silver_status, index_basic_status)
    ):
        return 1
    return blocked_fallback


def _cursor_payload(
    *,
    evaluated_at: datetime,
    target_trade_date: str | None,
    registered_trade_day_count: int,
    registered_code_count: int,
    selected_trade_date: str | None,
    reason: str,
    gold_status: AssetReadinessStatus | None = None,
    silver_status: AssetReadinessStatus | None = None,
    index_basic_status: AssetReadinessStatus | None = None,
    input_status: MarketMajorIndicesInputReadiness | None = None,
    blocked_fallback: int = 0,
) -> str:
    decision = (
        SensorCursorDecision.REQUEST_RUNS
        if selected_trade_date
        else SensorCursorDecision.SKIP
    )
    sample_keys = _input_sample_keys(input_status)
    if not sample_keys and selected_trade_date:
        sample_keys = (selected_trade_date,)
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_trade_date,
        selected_count=1 if selected_trade_date else 0,
        blocked_count=_blocked_count(
            selected_trade_date=selected_trade_date,
            blocked_fallback=blocked_fallback,
            gold_status=gold_status,
            silver_status=silver_status,
            index_basic_status=index_basic_status,
            input_status=input_status,
        ),
        sample_keys=sample_keys,
        details={
            "registered_trade_day_count": registered_trade_day_count,
            "registered_code_count": registered_code_count,
            "selected_trade_date": selected_trade_date,
            "reason": reason,
            "gold_status": _asset_status_payload(gold_status),
            "silver_status": _asset_status_payload(silver_status),
            "index_basic_status": _asset_status_payload(index_basic_status),
            "input_status": _input_status_payload(input_status),
        },
    )


@dg.sensor(
    job_name="market_major_indices_daily_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    description="指数日线 silver 和主要指数 seed 输入 ready 后，触发主要指数日线 gold 分区生成任务。",
)
def market_major_indices_daily_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    registered_trade_days = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_index_trade_days.name))
    )
    registered_index_codes = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_index_ts_codes.name))
    )

    if not registered_trade_days:
        reason = "没有注册指数交易日分区，无法触发主要指数日线 gold 生成。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=None,
            registered_trade_day_count=0,
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            reason=reason,
            blocked_fallback=1,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if not registered_index_codes:
        reason = "没有注册指数代码分区，无法触发主要指数日线 gold 生成。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=None,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=0,
            selected_trade_date=None,
            reason=reason,
            blocked_fallback=1,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    target_trade_date = _latest_registered_trade_date(registered_trade_days, evaluated_at)
    if target_trade_date is None:
        reason = "没有符合当前日期窗口的指数交易日分区。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=None,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            reason=reason,
            blocked_fallback=1,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    gold_status = gold_market_major_indices_daily_ready_for_trade_date(
        context.instance,
        target_trade_date,
    )
    if gold_status.ready:
        reason = (
            "最新指数交易日的 gold_market_major_indices_daily 分区已经生成完成并通过 "
            "blocking checks。"
        )
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            reason=reason,
            gold_status=gold_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    if gold_status.materialized:
        reason = (
            "最新指数交易日的 gold_market_major_indices_daily 已生成过，但 blocking "
            "checks 未全绿，暂不自动重跑，请人工检查后修复。"
        )
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            reason=reason,
            gold_status=gold_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    silver_status = silver_index_daily_ready_for_trade_date(
        context.instance,
        target_trade_date,
    )
    if not silver_status.ready:
        reason = "主要指数日线等待 silver_index_daily 目标分区 ready。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            reason=reason,
            gold_status=gold_status,
            silver_status=silver_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    index_basic_status = silver_index_basic_ready(context.instance)
    if not index_basic_status.ready:
        reason = "主要指数日线等待 silver_index_basic ready。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            reason=reason,
            gold_status=gold_status,
            silver_status=silver_status,
            index_basic_status=index_basic_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    input_status = check_market_major_indices_inputs_for_trade_date(
        lake_root_path=context.resources.lake_root.root(),
        duckdb=context.resources.duckdb,
        registered_index_codes=registered_index_codes,
        trade_date=target_trade_date,
    )
    if not input_status.ready:
        reason = (
            "主要指数日线输入门禁扫描失败，暂不触发 gold。"
            if input_status.scan_error
            else "主要指数日线 seed/input 门禁未满足，暂不触发 gold。"
        )
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            reason=reason,
            gold_status=gold_status,
            silver_status=silver_status,
            index_basic_status=index_basic_status,
            input_status=input_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    run_request = build_run_request(
        run_key=f"market_major_indices_daily:{target_trade_date}",
        partition_key=target_trade_date,
    )
    reason = "主要指数日线输入已 ready，提交 gold 分区生成。"
    cursor = _cursor_payload(
        evaluated_at=evaluated_at,
        target_trade_date=target_trade_date,
        registered_trade_day_count=len(registered_trade_days),
        registered_code_count=len(registered_index_codes),
        selected_trade_date=target_trade_date,
        reason=reason,
        gold_status=gold_status,
        silver_status=silver_status,
        index_basic_status=index_basic_status,
        input_status=input_status,
    )
    return dg.SensorResult(run_requests=[run_request], cursor=cursor)
