"""Stopped-by-default downstream sensor for stock nine-turn serving."""

from datetime import date

import dagster as dg

from orchestrator.defs.jobs.stock_daily_qfq_nineturn_prod_core_sync import (
    prod_core_stock_daily_qfq_nineturn_sync_job,
)
from orchestrator.defs.jobs.stock_daily_qfq_nineturn_update import (
    gold_stock_daily_qfq_nineturn_update_job,
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

DAGSTER_PARTITION_TAG = "dagster/partition"
SENSOR_NAME = "prod_core_stock_daily_qfq_nineturn_sync_job_sensor"
_CONSUMER = "prod_core_stock_daily_qfq_nineturn_sync"
_PRODUCER = "gold_stock_daily_qfq_nineturn_update"
_GOLD_READINESS_SPECS = (
    AssetReadinessSpec(
        asset_key=dg.AssetKey("gold_stock_daily_qfq_nineturn"),
        blocking_check_names=(
            "gold_stock_daily_qfq_nineturn_integrity_check",
        ),
    ),
)


def _normalized_partition_key(context: dg.RunStatusSensorContext) -> str | None:
    value = str(context.dagster_run.tags.get(DAGSTER_PARTITION_TAG) or "").strip()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _evaluate_sensor(
    context: dg.RunStatusSensorContext,
) -> dg.RunRequest | dg.SkipReason:
    partition_key = _normalized_partition_key(context)
    if partition_key is None:
        return dg.SkipReason("missing_target_trade_date: upstream run has no valid partition")
    readiness = partition_dataset_readiness_status_from_latest_checks(
        context.instance,
        _GOLD_READINESS_SPECS,
        partition_key=partition_key,
    )
    if not readiness.ready:
        return dg.SkipReason(f"gold_not_ready: {readiness.reason}")
    upstream_batch_id = build_batch_id(
        producer=_PRODUCER,
        scope=partition_key,
        payload={
            "producer_run_id": context.dagster_run.run_id,
            "partition_key": partition_key,
        },
    )
    return build_run_request(
        run_key=build_upstream_triggered_run_key(
            consumer=_CONSUMER,
            upstream_batch_id=upstream_batch_id,
        ),
        partition_key=partition_key,
    )


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    request_job=prod_core_stock_daily_qfq_nineturn_sync_job,
    monitored_jobs=[gold_stock_daily_qfq_nineturn_update_job],
    default_status=dg.DefaultSensorStatus.STOPPED,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.SERVING,
        role=SensorRole.ASSET_UPDATE,
    ),
    description=(
        "股票日线前复权九转 Gold 成功且 blocking check 通过后，提交同分区"
        " serving 发布；默认停止，完成历史发布验收后才允许启用。"
    ),
)
def prod_core_stock_daily_qfq_nineturn_sync_job_sensor(
    context: dg.RunStatusSensorContext,
) -> dg.RunRequest | dg.SkipReason:
    return _evaluate_sensor(context)
