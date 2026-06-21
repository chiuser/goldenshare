from datetime import datetime

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
    build_continuity_cursor_details,
    build_registered_gap_status,
    load_expected_trade_date_window,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.asset_guards.market_major_indices_lake_readiness import (
    batch_market_major_indices_lake_readiness,
    silver_index_basic_lake_readiness,
    silver_index_daily_lake_readiness_for_trade_date,
)
from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.market_major_indices_input_readiness import (
    MarketMajorIndicesInputReadiness,
    check_market_major_indices_inputs_for_trade_date,
)
from orchestrator.defs.sensors.readiness import (
    CN_A_SENSOR_TIMEZONE,
)
from orchestrator.defs.sensors.cn_a_trade_day_sensor import (
    INDEX_TRADE_DAY_MIN_DATE,
    SAME_DAY_PARTITION_REGISTER_START,
)


MAX_STATUS_SAMPLE_COUNT = 20


def _lake_status_payload(
    status: ContinuityDateReadiness | None,
) -> dict[str, object] | None:
    if status is None:
        return None
    return status.to_cursor_details()


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
    gold_status: ContinuityDateReadiness | None = None,
    silver_status: ContinuityDateReadiness | None = None,
    index_basic_status: ContinuityDateReadiness | None = None,
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
    continuity_status: dict[str, object] | None = None,
    gold_batch_status: ContinuityBatchReadiness | None = None,
    gold_status: ContinuityDateReadiness | None = None,
    silver_status: ContinuityDateReadiness | None = None,
    index_basic_status: ContinuityDateReadiness | None = None,
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
    reason_code = "request_run" if selected_trade_date else None
    blocked_component = None
    if reason_code is None and input_status is not None and not input_status.ready:
        reason_code = input_status.scan_error_code or "major_indices_input_not_ready"
        blocked_component = "market_major_indices_inputs"
    if reason_code is None:
        for component, status in (
            ("gold_market_major_indices_daily", gold_status),
            ("silver_index_daily", silver_status),
            ("silver_index_basic", index_basic_status),
        ):
            if status is not None and not status.ready:
                reason_code = status.reason
                blocked_component = component
                break
    if reason_code is None and continuity_status is not None:
        blocked_reason = continuity_status.get("blocked_reason")
        first_not_ready_reason = continuity_status.get("first_not_ready_reason")
        first_missing_registered_date = continuity_status.get(
            "first_missing_registered_date"
        )
        if first_missing_registered_date is not None:
            reason_code = "missing_registered_partition"
            blocked_component = "cn_a_index_trade_days"
        elif first_not_ready_reason:
            reason_code = str(first_not_ready_reason)
            blocked_component = "gold_market_major_indices_daily"
        elif blocked_reason:
            reason_code = str(blocked_reason)
            blocked_component = "gold_market_major_indices_daily"
    if reason_code is None:
        reason_code = "no_target_trade_date" if target_trade_date is None else "all_ready"
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
            "reason_code": reason_code,
            "blocked_component": blocked_component,
            "continuity_status": continuity_status,
            "gold_batch_status": (
                gold_batch_status.to_cursor_details() if gold_batch_status else None
            ),
            "gold_status": _lake_status_payload(gold_status),
            "silver_status": _lake_status_payload(silver_status),
            "index_basic_status": _lake_status_payload(index_basic_status),
            "input_status": _input_status_payload(input_status),
        },
    )


@dg.sensor(
    job_name="market_major_indices_daily_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
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

    lake_root_path = context.resources.lake_root.root()
    duckdb_resource = context.resources.duckdb
    with duckdb_resource.connect() as connection:
        expected_window = load_expected_trade_date_window(
            connection,
            silver_trade_calendar_path(lake_root_path),
            evaluated_at=evaluated_at,
            min_trade_date=INDEX_TRADE_DAY_MIN_DATE,
            same_day_register_start=SAME_DAY_PARTITION_REGISTER_START,
        )

    if not expected_window.expected_trade_dates:
        reason = "没有符合当前日期窗口的指数 expected trade date。"
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

    gap_status = build_registered_gap_status(
        expected_trade_dates=expected_window.expected_trade_dates,
        registered_trade_dates=registered_trade_days,
    )
    if not gap_status.ready:
        continuity_status = build_continuity_cursor_details(
            expected_window=expected_window,
            gap_status=gap_status,
            batch_readiness=None,
            selection=None,
        )
        reason = (
            "主要指数日线检测到指数交易日分区存在注册缺口，等待注册 sensor "
            f"补齐最早缺口 {gap_status.first_missing_registered_date}。"
        )
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=gap_status.first_missing_registered_date,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            reason=reason,
            continuity_status=continuity_status,
            blocked_fallback=1,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    with duckdb_resource.connect() as connection:
        gold_batch_status = batch_market_major_indices_lake_readiness(
            connection=connection,
            lake_root_path=lake_root_path,
            expected_trade_dates=expected_window.expected_trade_dates,
            registered_index_codes=registered_index_codes,
        )
    selection = select_first_not_ready_trade_date(
        expected_trade_dates=expected_window.expected_trade_dates,
        readiness=gold_batch_status,
    )
    continuity_status = build_continuity_cursor_details(
        expected_window=expected_window,
        gap_status=gap_status,
        batch_readiness=gold_batch_status,
        selection=selection,
    )
    target_trade_date = selection.first_not_ready_trade_date
    gold_status = selection.selected_status

    if selection.selected_trade_date is None:
        if selection.blocked_reason == "materialized_check_failed":
            reason = (
                "主要指数日线的 gold_market_major_indices_daily 已生成过，但 lake-derived "
                "blocking checks 未全绿，暂不自动重跑，请人工检查后修复。"
            )
            cursor = _cursor_payload(
                evaluated_at=evaluated_at,
                target_trade_date=target_trade_date,
                registered_trade_day_count=len(registered_trade_days),
                registered_code_count=len(registered_index_codes),
                selected_trade_date=None,
                reason=reason,
                continuity_status=continuity_status,
                gold_batch_status=gold_batch_status,
                gold_status=gold_status,
            )
            return dg.SensorResult(skip_reason=reason, cursor=cursor)

        reason = (
            "最近 10 个 expected index dates 的 gold_market_major_indices_daily "
            "都已通过 lake-derived blocking checks。"
        )
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            reason=reason,
            continuity_status=continuity_status,
            gold_batch_status=gold_batch_status,
            gold_status=gold_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    target_trade_date = selection.selected_trade_date
    assert target_trade_date is not None
    with duckdb_resource.connect() as connection:
        silver_status = silver_index_daily_lake_readiness_for_trade_date(
            connection=connection,
            lake_root_path=lake_root_path,
            trade_date=target_trade_date,
            registered_index_codes=registered_index_codes,
        )
    if not silver_status.ready:
        reason = (
            "主要指数日线等待 selected date 的 silver_index_daily lake readiness。"
        )
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            reason=reason,
            continuity_status=continuity_status,
            gold_batch_status=gold_batch_status,
            gold_status=gold_status,
            silver_status=silver_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    with duckdb_resource.connect() as connection:
        index_basic_status = silver_index_basic_lake_readiness(
            connection=connection,
            lake_root_path=lake_root_path,
            ready_for_trade_date=target_trade_date,
        )
    if not index_basic_status.ready:
        reason = "主要指数日线等待 silver_index_basic lake readiness。"
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            reason=reason,
            continuity_status=continuity_status,
            gold_batch_status=gold_batch_status,
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
            continuity_status=continuity_status,
            gold_batch_status=gold_batch_status,
            gold_status=gold_status,
            silver_status=silver_status,
            index_basic_status=index_basic_status,
            input_status=input_status,
        )
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    run_request = build_run_request(
        run_key=build_asset_update_run_key(
            subject="market_major_indices_daily",
            unit_id=target_trade_date,
        ),
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
        continuity_status=continuity_status,
        gold_batch_status=gold_batch_status,
        gold_status=gold_status,
        silver_status=silver_status,
        index_basic_status=index_basic_status,
        input_status=input_status,
    )
    return dg.SensorResult(run_requests=[run_request], cursor=cursor)
