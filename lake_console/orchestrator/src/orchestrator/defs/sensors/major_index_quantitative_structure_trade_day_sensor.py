"""Register recent SSE dates for the Gold dataset."""

from datetime import datetime

import dagster as dg

from orchestrator.defs.io.major_index_quantitative_structure import (
    structure_trade_dates,
)
from orchestrator.defs.partitions import (
    cn_major_index_quantitative_structure_trade_days,
)
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.major_index_quantitative_structure import (
    STRUCTURE_CHECK_START,
    STRUCTURE_REGISTRATION_LIMIT,
    STRUCTURE_SENSOR_INTERVAL_SECONDS,
    STRUCTURE_SENSOR_LOOKBACK,
)
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE


@dg.sensor(
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=STRUCTURE_SENSOR_INTERVAL_SECONDS,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.PARTITION,
        role=SensorRole.PARTITION_REGISTRATION,
    ),
    description="上海时间 18:00 起登记量化结构交易日分区并补近期缺口。",
)
def major_index_quantitative_structure_trade_day_sensor(
    context: dg.SensorEvaluationContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.SensorResult:
    now = datetime.now(CN_A_SENSOR_TIMEZONE)
    if now.time() < STRUCTURE_CHECK_START:
        return dg.SensorResult(skip_reason="上海时间 18:00 起检查量化结构分区。")
    if not silver_trade_calendar_path(lake_root.root()).is_file():
        return dg.SensorResult(skip_reason="等待 SSE 交易日历文件。")
    with duckdb.connect() as connection:
        days = structure_trade_dates(
            connection, lake_root.root(), now.date(),
            recent=STRUCTURE_SENSOR_LOOKBACK,
        )
    partition_set = cn_major_index_quantitative_structure_trade_days
    missing = []
    for day in days:
        key = day.isoformat()
        if not context.instance.has_dynamic_partition(partition_set.name, key):
            missing.append(key)
        if len(missing) == STRUCTURE_REGISTRATION_LIMIT:
            break
    summary = "补登记量化结构交易日分区。" if missing else "近期量化结构分区已登记。"
    cursor = build_sensor_cursor(
        evaluated_at=now,
        decision=SensorCursorDecision.REGISTER_PARTITIONS if missing else SensorCursorDecision.SKIP,
        target_date=missing[0] if missing else None,
        selected_count=len(missing),
        sample_keys=missing,
        details={"summary": summary, "next_action": "等待下次检查。"},
    )
    if missing:
        return dg.SensorResult(
            dynamic_partitions_requests=[partition_set.build_add_request(missing)],
            cursor=cursor,
        )
    return dg.SensorResult(skip_reason=summary, cursor=cursor)
