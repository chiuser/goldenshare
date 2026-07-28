"""Dedicated natural-day partition registration for international indexes."""

from datetime import date, datetime, timedelta

import dagster as dg

from orchestrator.defs.partitions import cn_global_index_trade_days
from orchestrator.defs.run_contracts.cursor_payloads import build_cursor_details
from orchestrator.defs.run_contracts.cursors import SensorCursorDecision, build_sensor_cursor
from orchestrator.defs.run_contracts.index_global import (
    GLOBAL_INDEX_PARTITION_REGISTRATION_BATCH_SIZE,
    GLOBAL_INDEX_START_DATE,
)
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE


SENSOR_NAME = "global_index_trade_day_partition_sensor"


def _natural_days_through(today: date) -> tuple[str, ...]:
    start = date.fromisoformat(GLOBAL_INDEX_START_DATE)
    if today < start:
        return ()
    count = (today - start).days + 1
    return tuple((start + timedelta(days=offset)).isoformat() for offset in range(count))


def evaluate_global_index_partition_sensor(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime,
) -> dg.SensorResult:
    today = evaluated_at.astimezone(CN_A_SENSOR_TIMEZONE).date()
    expected = _natural_days_through(today)
    existing = set(context.instance.get_dynamic_partitions(cn_global_index_trade_days.name))
    missing = tuple(key for key in expected if key not in existing)
    selected = missing[:GLOBAL_INDEX_PARTITION_REGISTRATION_BATCH_SIZE]
    decision = (
        SensorCursorDecision.REGISTER_PARTITIONS
        if selected
        else SensorCursorDecision.SKIP
    )
    cursor = build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=selected[-1] if selected else (expected[-1] if expected else None),
        selected_count=len(selected),
        blocked_count=max(0, len(missing) - len(selected)),
        sample_keys=selected[:3],
        details=build_cursor_details(
            sensor_name=SENSOR_NAME,
            job_name=None,
            asset_family="index_global_partition_registration",
            partition_set=cn_global_index_trade_days.name,
            reason_code="register_partitions" if selected else "all_registered",
            blocked_component="none",
            summary=(
                f"register {len(selected)} natural-day partitions"
                if selected
                else "all natural-day partitions through today are registered"
            ),
            next_action=(
                "wait for the next registration tick"
                if not selected
                else "wait for registration to be committed"
            ),
            frontier={
                "start_date": GLOBAL_INDEX_START_DATE,
                "today": today.isoformat(),
                "expected_count": len(expected),
                "registered_count": len(existing),
            },
            evidence={
                "batch_limit": GLOBAL_INDEX_PARTITION_REGISTRATION_BATCH_SIZE,
                "source_reads": 0,
                "event_history_reads": 0,
            },
        ),
    )
    return dg.SensorResult(
        dynamic_partitions_requests=(
            [cn_global_index_trade_days.build_add_request(list(selected))]
            if selected
            else []
        ),
        skip_reason=None if selected else dg.SkipReason("all_registered: no natural-day partitions pending"),
        cursor=cursor,
    )


@dg.sensor(
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.PARTITION,
        role=SensorRole.PARTITION_REGISTRATION,
    ),
    description="为国际指数独立注册 2022-01-01 起的自然日分区，不依赖 SSE 交易日历。",
)
def global_index_trade_day_partition_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return evaluate_global_index_partition_sensor(
        context,
        evaluated_at=datetime.now(CN_A_SENSOR_TIMEZONE),
    )


__all__ = ["evaluate_global_index_partition_sensor", "global_index_trade_day_partition_sensor"]
