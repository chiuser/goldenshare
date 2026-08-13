"""Daily sensor for canonical major-index Gold minute bars."""

import dagster as dg

from orchestrator.defs.asset_guards.major_index_mins_gold import (
    batch_gold_major_index_mins_lake_readiness,
)
from orchestrator.defs.asset_guards.major_index_mins_lake_readiness import (
    batch_silver_major_index_mins_lake_readiness,
)
from orchestrator.defs.partitions import cn_major_index_mins_trade_days
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_GOLD_JOB_NAME,
    MAJOR_INDEX_MINS_GOLD_SENSOR_NAME,
    MAJOR_INDEX_MINS_HISTORY_START_DATE,
)
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.cn_a_gold_minute_sensor import (
    CanonicalGoldMinuteSensorSpec,
    evaluate_canonical_gold_minute_sensor,
)

_SPEC = CanonicalGoldMinuteSensorSpec(
    sensor_name=MAJOR_INDEX_MINS_GOLD_SENSOR_NAME,
    job_name=MAJOR_INDEX_MINS_GOLD_JOB_NAME,
    asset_family="major_index_mins",
    min_trade_date=MAJOR_INDEX_MINS_HISTORY_START_DATE,
    partition_set_name=cn_major_index_mins_trade_days.name,
    silver_readiness_loader=batch_silver_major_index_mins_lake_readiness,
    gold_readiness_loader=batch_gold_major_index_mins_lake_readiness,
)


@dg.sensor(
    name=MAJOR_INDEX_MINS_GOLD_SENSOR_NAME,
    job_name=MAJOR_INDEX_MINS_GOLD_JOB_NAME,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
)
def gold_major_index_mins_update_job_sensor(context: dg.SensorEvaluationContext):
    return evaluate_canonical_gold_minute_sensor(context, spec=_SPEC)


__all__ = ["gold_major_index_mins_update_job_sensor"]
