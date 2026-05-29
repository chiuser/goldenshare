from dataclasses import dataclass
from datetime import datetime, time

import dagster as dg

from orchestrator.defs.partitions import cn_a_stock_current_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.sensors.cn_a_trade_day_sensor import is_sse_open_day
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE


STOCK_CURRENT_TRADE_DAY_REGISTER_START = time(6, 0)


@dataclass(frozen=True)
class StockCurrentTradeDayRegistrationDecision:
    today: str
    today_is_open: bool
    register_window_started: bool
    already_registered: bool
    selected_keys: tuple[str, ...]


def build_stock_current_trade_day_registration_decision(
    *,
    today: str,
    today_is_open: bool,
    register_window_started: bool,
    already_registered: bool,
) -> StockCurrentTradeDayRegistrationDecision:
    selected_keys = (
        (today,)
        if today_is_open and register_window_started and not already_registered
        else ()
    )
    return StockCurrentTradeDayRegistrationDecision(
        today=today,
        today_is_open=today_is_open,
        register_window_started=register_window_started,
        already_registered=already_registered,
        selected_keys=selected_keys,
    )


def _cursor_payload(
    *,
    decision: StockCurrentTradeDayRegistrationDecision,
    evaluated_at: datetime,
) -> str:
    cursor_decision = (
        SensorCursorDecision.REGISTER_PARTITIONS
        if decision.selected_keys
        else SensorCursorDecision.SKIP
    )
    blocked_count = (
        1
        if not decision.selected_keys
        and decision.today_is_open
        and not decision.already_registered
        else 0
    )
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=cursor_decision,
        target_date=decision.today,
        selected_count=len(decision.selected_keys),
        blocked_count=blocked_count,
        sample_keys=decision.selected_keys,
        details={
            "today": decision.today,
            "today_is_open": decision.today_is_open,
            "register_window_started": decision.register_window_started,
            "already_registered": decision.already_registered,
            "selected_keys": list(decision.selected_keys),
            "partition_set": cn_a_stock_current_trade_days.name,
        },
    )


def _skip_reason(decision: StockCurrentTradeDayRegistrationDecision) -> str:
    if not decision.today_is_open:
        return "今天不是上交所开市日，不注册股票当前交易日分区。"
    if not decision.register_window_started:
        return "今天是交易日，但还没到 06:00，暂不注册股票当前交易日分区。"
    if decision.already_registered:
        return "今天的股票当前交易日分区已经注册。"
    return "当前没有需要注册的股票当前交易日分区。"


@dg.sensor(
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    description="每天 06:00 后注册当天股票当前交易日分区，不触发数据更新任务。",
)
def stock_current_trade_day_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    today = evaluated_at.date().isoformat()
    register_window_started = (
        evaluated_at.time() >= STOCK_CURRENT_TRADE_DAY_REGISTER_START
    )

    lake_root = context.resources.lake_root
    duckdb_resource = context.resources.duckdb
    lake_root.ensure_available_for_run()
    calendar_path = silver_trade_calendar_path(lake_root.root())
    if not calendar_path.exists():
        raise FileNotFoundError(f"silver_trade_calendar file is missing: {calendar_path}")

    with duckdb_resource.connect() as connection:
        today_is_open = is_sse_open_day(connection, calendar_path, today)

    registered_keys = set(
        context.instance.get_dynamic_partitions(cn_a_stock_current_trade_days.name)
    )
    decision = build_stock_current_trade_day_registration_decision(
        today=today,
        today_is_open=today_is_open,
        register_window_started=register_window_started,
        already_registered=today in registered_keys,
    )
    cursor = _cursor_payload(decision=decision, evaluated_at=evaluated_at)

    if not decision.selected_keys:
        return dg.SensorResult(skip_reason=_skip_reason(decision), cursor=cursor)

    return dg.SensorResult(
        dynamic_partitions_requests=[
            cn_a_stock_current_trade_days.build_add_request(list(decision.selected_keys))
        ],
        cursor=cursor,
    )
