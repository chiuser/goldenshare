from datetime import datetime, time

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    DEFAULT_CONTINUITY_WINDOW_LIMIT,
    ContinuityExpectedDateWindow,
    ContinuityRegisteredGapStatus,
    build_registered_gap_status,
    load_expected_trade_date_window,
)
from orchestrator.defs.partitions import cn_a_stock_current_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.cn_a_trade_day_sensor import is_sse_open_day
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE


STOCK_CURRENT_TRADE_DAY_REGISTER_START = time(6, 0)
STOCK_CURRENT_TRADE_DAY_MAX_PARTITIONS_PER_TICK = 2


def _format_register_start(register_start: time) -> str:
    return register_start.strftime("%H:%M")


def _selected_partition_keys(
    gap_status: ContinuityRegisteredGapStatus,
) -> tuple[str, ...]:
    return gap_status.missing_registered_dates[
        :STOCK_CURRENT_TRADE_DAY_MAX_PARTITIONS_PER_TICK
    ]


def _cursor_payload(
    *,
    expected_window: ContinuityExpectedDateWindow,
    gap_status: ContinuityRegisteredGapStatus,
    selected_keys: tuple[str, ...],
    evaluated_at: datetime,
) -> str:
    cursor_decision = (
        SensorCursorDecision.REGISTER_PARTITIONS
        if selected_keys
        else SensorCursorDecision.SKIP
    )
    missing_registered_count = max(
        0,
        len(expected_window.expected_trade_dates) - len(gap_status.registered_trade_dates),
    )
    blocked_count = max(
        0,
        missing_registered_count - len(selected_keys),
    )
    gap_details = gap_status.to_cursor_details()
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=cursor_decision,
        target_date=gap_status.first_missing_registered_date
        or expected_window.max_trade_date,
        selected_count=len(selected_keys),
        blocked_count=blocked_count,
        sample_keys=selected_keys,
        details={
            "partition_set": cn_a_stock_current_trade_days.name,
            "expected_start_date": gap_details["expected_start_date"],
            "expected_end_date": gap_details["expected_end_date"],
            "expected_count": gap_details["expected_count"],
            "registered_count": gap_details["registered_count"],
            "missing_registered_count": missing_registered_count,
            "first_missing_registered_date": gap_status.first_missing_registered_date,
            "missing_registered_dates": list(gap_status.missing_registered_dates),
            "selected_keys": list(selected_keys),
            "same_day_register_start": _format_register_start(
                STOCK_CURRENT_TRADE_DAY_REGISTER_START
            ),
            "window_limit": expected_window.window_limit,
            "max_partition_keys_per_tick": (
                STOCK_CURRENT_TRADE_DAY_MAX_PARTITIONS_PER_TICK
            ),
        },
    )


def _skip_reason(
    *,
    expected_window: ContinuityExpectedDateWindow,
    today_is_open: bool,
    register_window_started: bool,
) -> str:
    if not expected_window.expected_trade_dates:
        return "没有从交易日历中找到符合条件的上交所开市日。"
    if today_is_open and not register_window_started:
        return "今天是交易日，但还没到 06:00，暂不注册股票当前交易日分区。"
    return "当前最近 60 个股票当前交易日分区都已经注册。"


@dg.sensor(
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.PARTITION,
        role=SensorRole.PARTITION_REGISTRATION,
    ),
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
        expected_window = load_expected_trade_date_window(
            connection,
            calendar_path,
            evaluated_at=evaluated_at,
            same_day_register_start=STOCK_CURRENT_TRADE_DAY_REGISTER_START,
            window_limit=DEFAULT_CONTINUITY_WINDOW_LIMIT,
        )
        today_is_open = is_sse_open_day(connection, calendar_path, today)

    registered_keys = set(
        context.instance.get_dynamic_partitions(cn_a_stock_current_trade_days.name)
    )
    gap_status = build_registered_gap_status(
        expected_trade_dates=expected_window.expected_trade_dates,
        registered_trade_dates=registered_keys,
    )
    selected_keys = _selected_partition_keys(gap_status)
    cursor = _cursor_payload(
        expected_window=expected_window,
        gap_status=gap_status,
        selected_keys=selected_keys,
        evaluated_at=evaluated_at,
    )

    if not selected_keys:
        return dg.SensorResult(
            skip_reason=_skip_reason(
                expected_window=expected_window,
                today_is_open=today_is_open,
                register_window_started=register_window_started,
            ),
            cursor=cursor,
        )

    return dg.SensorResult(
        dynamic_partitions_requests=[
            cn_a_stock_current_trade_days.build_add_request(list(selected_keys))
        ],
        cursor=cursor,
    )
