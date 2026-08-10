"""Current-day partition registration for daily index technical factors."""

from datetime import datetime

import dagster as dg

from orchestrator.defs.partitions import cn_major_index_factor_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursor_payloads import build_cursor_details
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_PARTITION_SENSOR_NAME,
)
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.cn_a_trade_day_sensor import (
    SAME_DAY_PARTITION_REGISTER_START,
    is_sse_open_day,
)
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE


def _cursor(
    *,
    evaluated_at: datetime,
    trade_date: str,
    reason_code: str,
    selected: bool,
) -> str:
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=(
            SensorCursorDecision.REGISTER_PARTITIONS
            if selected
            else SensorCursorDecision.SKIP
        ),
        target_date=trade_date,
        selected_count=1 if selected else 0,
        blocked_count=0 if selected or reason_code == "already_registered" else 1,
        sample_keys=(trade_date,) if selected else (),
        details=build_cursor_details(
            sensor_name=IDX_FACTOR_PRO_PARTITION_SENSOR_NAME,
            job_name=None,
            asset_family="idx_factor_pro",
            partition_set=cn_major_index_factor_trade_days.name,
            reason_code=reason_code,
            blocked_component=(
                "none"
                if selected or reason_code == "already_registered"
                else reason_code
            ),
            summary=(
                "register the current idx_factor_pro trade-date partition"
                if selected
                else f"idx_factor_pro partition registration skipped: {reason_code}"
            ),
            next_action=(
                "wait for the Raw sensor tick"
                if selected
                else "wait for the next partition sensor tick"
            ),
            frontier={"current_trade_date": trade_date},
            evidence={"max_partition_keys_per_tick": 1},
        ),
    )


def _evaluate_idx_factor_pro_trade_day_sensor(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime,
) -> dg.SensorResult:
    trade_date = evaluated_at.date().isoformat()
    if evaluated_at.timetz().replace(tzinfo=None) < SAME_DAY_PARTITION_REGISTER_START:
        return dg.SensorResult(
            skip_reason="尚未到 16:00，不注册当天指数技术因子分区。",
            cursor=_cursor(
                evaluated_at=evaluated_at,
                trade_date=trade_date,
                reason_code="before_closing_window",
                selected=False,
            ),
        )

    try:
        lake_root = context.resources.lake_root
        lake_root.ensure_available_for_run()
        calendar_path = silver_trade_calendar_path(lake_root.root())
        if not calendar_path.exists():
            raise FileNotFoundError(
                f"silver_trade_calendar file is missing: {calendar_path}"
            )
        duckdb_resource = context.resources.duckdb
        with duckdb_resource.connect() as connection:
            today_is_open = is_sse_open_day(connection, calendar_path, trade_date)
        if not today_is_open:
            return dg.SensorResult(
                skip_reason="当天不是上交所开市日，不注册指数技术因子分区。",
                cursor=_cursor(
                    evaluated_at=evaluated_at,
                    trade_date=trade_date,
                    reason_code="current_date_not_open",
                    selected=False,
                ),
            )

        registered = set(
            context.instance.get_dynamic_partitions(
                cn_major_index_factor_trade_days.name
            )
        )
        if trade_date in registered:
            return dg.SensorResult(
                skip_reason="当天指数技术因子分区已经注册。",
                cursor=_cursor(
                    evaluated_at=evaluated_at,
                    trade_date=trade_date,
                    reason_code="already_registered",
                    selected=False,
                ),
            )
        return dg.SensorResult(
            dynamic_partitions_requests=[
                cn_major_index_factor_trade_days.build_add_request([trade_date])
            ],
            cursor=_cursor(
                evaluated_at=evaluated_at,
                trade_date=trade_date,
                reason_code="register_current_partition",
                selected=True,
            ),
        )
    except Exception:  # noqa: BLE001 - sensor fails closed.
        return dg.SensorResult(
            skip_reason="指数技术因子分区 sensor 执行失败，已 fail-closed。",
            cursor=_cursor(
                evaluated_at=evaluated_at,
                trade_date=trade_date,
                reason_code="sensor_error",
                selected=False,
            ),
        )


@dg.sensor(
    name=IDX_FACTOR_PRO_PARTITION_SENSOR_NAME,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.PARTITION,
        role=SensorRole.PARTITION_REGISTRATION,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description="16:00 后只注册当天的主要指数技术因子专属交易日分区。",
)
def idx_factor_pro_trade_day_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return _evaluate_idx_factor_pro_trade_day_sensor(
        context,
        evaluated_at=datetime.now(CN_A_SENSOR_TIMEZONE),
    )


__all__ = [
    "_evaluate_idx_factor_pro_trade_day_sensor",
    "idx_factor_pro_trade_day_sensor",
]
