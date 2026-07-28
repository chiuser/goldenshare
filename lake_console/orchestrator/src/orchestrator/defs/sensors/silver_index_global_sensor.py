"""Final-phase Raw -> Silver handoff for international indexes."""

from collections.abc import Mapping

import dagster as dg

from orchestrator.defs.asset_guards.index_global_lake_readiness import (
    silver_index_global_file_status,
)
from orchestrator.defs.jobs.index_global import (
    raw_index_global_update_job,
    silver_index_global_update_job,
)
from orchestrator.defs.partitions import cn_global_index_trade_days
from orchestrator.defs.paths import silver_index_global_path
from orchestrator.defs.run_contracts.index_global import (
    build_index_global_silver_run_config,
    parse_index_global_raw_run_config,
    validate_index_global_raw_config,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)


def _skip(code: str, detail: str) -> dg.SkipReason:
    return dg.SkipReason(f"{code}: {detail}")


def evaluate_silver_index_global_sensor(
    context: dg.RunStatusSensorContext,
) -> dg.RunRequest | dg.SkipReason:
    dagster_run = context.dagster_run
    run_config = getattr(dagster_run, "run_config", None)
    if not isinstance(run_config, Mapping):
        return _skip("missing_typed_run_config", "successful Raw run has no run_config")
    try:
        raw_config = parse_index_global_raw_run_config(run_config)
        trade_date = validate_index_global_raw_config(
            raw_config,
            partition_key=raw_config.trade_date,
        )
    except (TypeError, ValueError) as error:
        return _skip("invalid_typed_run_config", str(error)[:300])
    if raw_config.probe_phase != "americas":
        return _skip("phase_not_final", "only Americas success enters Silver")

    registered = set(context.instance.get_dynamic_partitions(cn_global_index_trade_days.name))
    if trade_date not in registered:
        return _skip("partition_not_registered", trade_date)

    lake_root = context.resources.lake_root
    lake_root.ensure_available_for_run()
    path = silver_index_global_path(lake_root.root(), trade_date)
    duckdb_resource = context.resources.duckdb
    with duckdb_resource.connect() as connection:
        status = silver_index_global_file_status(
            connection,
            path,
            partition_key=trade_date,
        )
    if status.reason_code == "core_contract_failed" or status.reason_code == "schema_mismatch":
        return _skip(
            "silver_existing_check_failed",
            "existing Silver file is invalid and will not be overwritten automatically",
        )

    return build_run_request(
        run_key=build_asset_update_run_key(
            subject="silver_index_global_update",
            unit_id=trade_date,
        ),
        partition_key=trade_date,
        run_config=build_index_global_silver_run_config(trade_date=trade_date),
    )


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    request_job=silver_index_global_update_job,
    monitored_jobs=[raw_index_global_update_job],
    default_status=dg.DefaultSensorStatus.STOPPED,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="只消费 Raw Americas 成功 run 的 typed config，触发同日 Silver。",
)
def silver_index_global_update_job_sensor(
    context: dg.RunStatusSensorContext,
) -> dg.RunRequest | dg.SkipReason:
    return evaluate_silver_index_global_sensor(context)


__all__ = ["evaluate_silver_index_global_sensor", "silver_index_global_update_job_sensor"]
