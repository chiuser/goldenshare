"""Bounded typed-config retries for failed international-index Raw runs."""

from collections.abc import Mapping

import dagster as dg

from orchestrator.defs.jobs.index_global import raw_index_global_update_job
from orchestrator.defs.run_contracts.index_global import (
    GLOBAL_INDEX_FAILED_RUN_RETRY_LIMIT,
    build_index_global_raw_run_config,
    parse_index_global_raw_run_config,
    validate_index_global_raw_config,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_repair_attempt_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)


def _skip(code: str, detail: str) -> dg.SkipReason:
    return dg.SkipReason(f"{code}: {detail}")


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.FAILURE,
    request_job=raw_index_global_update_job,
    monitored_jobs=[raw_index_global_update_job],
    default_status=dg.DefaultSensorStatus.STOPPED,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="读取失败 Raw run 的 typed config，最多重试两次，不扫描 event history。",
)
def raw_index_global_retry_sensor(
    context: dg.RunStatusSensorContext,
) -> dg.RunRequest | dg.SkipReason:
    run_config = getattr(context.dagster_run, "run_config", None)
    if not isinstance(run_config, Mapping):
        return _skip("missing_typed_run_config", "failed run has no run_config")
    try:
        config = parse_index_global_raw_run_config(run_config)
        partition_key = validate_index_global_raw_config(
            config,
            partition_key=config.trade_date,
        )
    except (TypeError, ValueError) as error:
        return _skip("invalid_typed_run_config", str(error)[:300])
    if config.probe_phase == "late_empty":
        return _skip("late_empty_uses_dedicated_sensor", "normal failure retry is not used")
    next_attempt = config.attempt + 1
    if next_attempt > GLOBAL_INDEX_FAILED_RUN_RETRY_LIMIT:
        return _skip("retry_exhausted", "Raw retry limit reached")
    run_config = build_index_global_raw_run_config(
        trade_date=partition_key,
        probe_phase=config.probe_phase,
        slot_key=config.slot_key,
        attempt=next_attempt,
    )
    return build_run_request(
        run_key=build_repair_attempt_run_key(
            subject="index_global_update",
            repair_scope_id=f"{partition_key}:{config.probe_phase}",
            attempt=next_attempt,
            attempt_scope="retry",
        ),
        partition_key=partition_key,
        run_config=run_config,
    )


__all__ = ["raw_index_global_retry_sensor"]
