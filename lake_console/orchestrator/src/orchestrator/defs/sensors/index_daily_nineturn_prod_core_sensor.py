"""Stopped-by-default downstream sensor for index nine-turn serving."""

from datetime import date

import dagster as dg

from orchestrator.defs.jobs.index_daily_nineturn_prod_core_sync import (
    prod_core_index_daily_nineturn_sync_job,
)
from orchestrator.defs.jobs.major_index_nineturn_update import (
    gold_major_index_daily_nineturn_update_job,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import (
    build_batch_id,
    build_upstream_triggered_run_key,
)
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    partition_dataset_readiness_status_from_latest_checks,
)

_GOLD_SPEC = (
    AssetReadinessSpec(
        asset_key=dg.AssetKey("gold_major_index_daily_nineturn"),
        blocking_check_names=("gold_major_index_daily_nineturn_integrity_check",),
    ),
)


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    request_job=prod_core_index_daily_nineturn_sync_job,
    monitored_jobs=[gold_major_index_daily_nineturn_update_job],
    default_status=dg.DefaultSensorStatus.STOPPED,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.SERVING,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="指数日线九转 Gold 同分区 blocking check 通过后发布 serving；默认停止。",
)
def prod_core_index_daily_nineturn_sync_job_sensor(
    context: dg.RunStatusSensorContext,
) -> dg.RunRequest | dg.SkipReason:
    raw_partition = str(context.dagster_run.tags.get("dagster/partition") or "").strip()
    try:
        partition_key = date.fromisoformat(raw_partition).isoformat()
    except ValueError:
        return dg.SkipReason("upstream run has no valid partition")
    readiness = partition_dataset_readiness_status_from_latest_checks(
        context.instance,
        _GOLD_SPEC,
        partition_key=partition_key,
    )
    if not readiness.ready:
        return dg.SkipReason(f"gold_not_ready: {readiness.reason}")
    batch_id = build_batch_id(
        producer="gold_major_index_daily_nineturn_update",
        scope=partition_key,
        payload={
            "producer_run_id": context.dagster_run.run_id,
            "partition_key": partition_key,
        },
    )
    return build_run_request(
        run_key=build_upstream_triggered_run_key(
            consumer="prod_core_index_daily_nineturn_sync",
            upstream_batch_id=batch_id,
        ),
        partition_key=partition_key,
    )
