"""Register stock trend-channel trade-day partitions after 06:00."""

from datetime import datetime, time

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    DEFAULT_CONTINUITY_WINDOW_LIMIT,
    ContinuityExpectedDateWindow,
    ContinuityRegisteredGapStatus,
    build_registered_gap_status,
    load_expected_trade_date_window,
)
from orchestrator.defs.partitions import (
    cn_a_stock_daily_trend_channel_trade_days,
)
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursor_payloads import (
    build_cursor_details,
    compact_continuity_frontier,
)
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

STOCK_DAILY_TREND_CHANNEL_REGISTER_START = time(6, 0)
STOCK_DAILY_TREND_CHANNEL_MAX_PARTITIONS_PER_TICK = 2


def _selected_partition_keys(
    gap_status: ContinuityRegisteredGapStatus,
) -> tuple[str, ...]:
    return gap_status.missing_registered_dates[
        :STOCK_DAILY_TREND_CHANNEL_MAX_PARTITIONS_PER_TICK
    ]


def _cursor_payload(
    *,
    expected_window: ContinuityExpectedDateWindow,
    gap_status: ContinuityRegisteredGapStatus,
    selected_keys: tuple[str, ...],
    evaluated_at: datetime,
) -> str:
    missing_count = max(
        0,
        len(expected_window.expected_trade_dates)
        - len(gap_status.registered_trade_dates),
    )
    blocked_count = max(0, missing_count - len(selected_keys))
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=(
            SensorCursorDecision.REGISTER_PARTITIONS
            if selected_keys
            else SensorCursorDecision.SKIP
        ),
        target_date=(
            gap_status.first_missing_registered_date
            or expected_window.max_trade_date
        ),
        selected_count=len(selected_keys),
        blocked_count=blocked_count,
        sample_keys=selected_keys,
        details=build_cursor_details(
            sensor_name="stock_daily_trend_channel_trade_day_sensor",
            job_name=None,
            asset_family="stock_daily_trend_channel_partitions",
            partition_set=cn_a_stock_daily_trend_channel_trade_days.name,
            reason_code=(
                "register_partitions" if selected_keys else "all_registered"
            ),
            blocked_component=(
                cn_a_stock_daily_trend_channel_trade_days.name
                if blocked_count
                else "none"
            ),
            summary=(
                f"已触发：注册 {len(selected_keys)} 个股票趋势通道交易日分区。"
                if selected_keys
                else "未触发：最近股票趋势通道交易日分区都已注册。"
            ),
            next_action=(
                "等待 Dagster dynamic partition 注册完成。"
                if selected_keys
                else "无需处理，等待下一次 sensor tick。"
            ),
            frontier=compact_continuity_frontier(
                gap_status,
                selected_trade_date=(selected_keys[0] if selected_keys else None),
            ),
            evidence={
                "missing_registered_count": missing_count,
                "same_day_register_start": (
                    STOCK_DAILY_TREND_CHANNEL_REGISTER_START.strftime("%H:%M")
                ),
                "window_limit": expected_window.window_limit,
                "max_partition_keys_per_tick": (
                    STOCK_DAILY_TREND_CHANNEL_MAX_PARTITIONS_PER_TICK
                ),
            },
        ),
    )


@dg.sensor(
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.PARTITION,
        role=SensorRole.PARTITION_REGISTRATION,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description=(
        "每天 06:00 后按 SSE 交易日历补注册股票趋势通道专属分区，"
        "每 tick 最多 2 个，只注册、不触发计算。"
    ),
)
def stock_daily_trend_channel_trade_day_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    today = evaluated_at.date().isoformat()
    register_window_started = (
        evaluated_at.time() >= STOCK_DAILY_TREND_CHANNEL_REGISTER_START
    )
    lake_root = context.resources.lake_root
    duckdb_resource = context.resources.duckdb
    lake_root.ensure_available_for_run()
    calendar_path = silver_trade_calendar_path(lake_root.root())
    if not calendar_path.is_file():
        raise FileNotFoundError(
            f"silver_trade_calendar file is missing: {calendar_path}"
        )

    with duckdb_resource.connect() as connection:
        expected_window = load_expected_trade_date_window(
            connection,
            calendar_path,
            evaluated_at=evaluated_at,
            same_day_register_start=STOCK_DAILY_TREND_CHANNEL_REGISTER_START,
            window_limit=DEFAULT_CONTINUITY_WINDOW_LIMIT,
        )
        today_is_open = is_sse_open_day(connection, calendar_path, today)

    registered_keys = context.instance.get_dynamic_partitions(
        cn_a_stock_daily_trend_channel_trade_days.name
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
        if (
            today_is_open
            and not register_window_started
        ):
            reason = "今天是交易日，但还没到 06:00，暂不注册趋势通道分区。"
        elif not expected_window.expected_trade_dates:
            reason = "交易日历中没有可注册的 SSE 开市日。"
        else:
            reason = "最近 10 个股票趋势通道交易日分区均已注册。"
        return dg.SensorResult(skip_reason=reason, cursor=cursor)

    return dg.SensorResult(
        dynamic_partitions_requests=[
            cn_a_stock_daily_trend_channel_trade_days.build_add_request(
                list(selected_keys)
            )
        ],
        cursor=cursor,
    )
