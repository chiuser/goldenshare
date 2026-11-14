"""Independent, STOPPED 同花顺个股 registration and update sensors."""

from datetime import datetime

import dagster as dg
from dagster._core.event_api import PartitionKeyFilter
from dagster._core.storage.asset_check_execution_record import (
    AssetCheckExecutionRecordStatus,
)

from orchestrator.defs.io.moneyflow_candidates import candidate_file_hash
from orchestrator.defs.jobs.moneyflow_ths import (
    raw_tushare_moneyflow_ths_update_job,
    silver_moneyflow_ths_update_job,
)
from orchestrator.defs.partitions import cn_a_moneyflow_ths_trade_days
from orchestrator.defs.paths import silver_moneyflow_path
from orchestrator.defs.resources import LakeRootResource
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_SENSOR_INTERVAL,
    MONEYFLOW_THS_READINESS_FILE_MAX_BYTES,
    MONEYFLOW_THS_SILVER_CHECK,
)
from orchestrator.defs.run_contracts.moneyflow_automation import (
    STOCK_THS_MONEYFLOW_AUTOMATION,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.moneyflow_update_selection import (
    evaluate_moneyflow_update,
    register_moneyflow_trade_days,
)
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE

RAW_JOB = STOCK_THS_MONEYFLOW_AUTOMATION.raw_job
SILVER_JOB = STOCK_THS_MONEYFLOW_AUTOMATION.silver_job
PARTITIONS = cn_a_moneyflow_ths_trade_days.name


def evaluate_stock_moneyflow_ths(context, now):
    return evaluate_moneyflow_update(
        context, now, contract=STOCK_THS_MONEYFLOW_AUTOMATION
    )


@dg.sensor(
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=MONEYFLOW_SENSOR_INTERVAL,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.PARTITION,
        role=SensorRole.PARTITION_REGISTRATION,
    ),
    description=f"上海{STOCK_THS_MONEYFLOW_AUTOMATION.register_start:%H:%M}后优先登记同花顺个股资金流当日，最多补一个接续漏登记日，不提交job。",
)
def cn_a_moneyflow_ths_trade_day_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return register_moneyflow_trade_days(
        context,
        contract=STOCK_THS_MONEYFLOW_AUTOMATION,
        dynamic_partitions=cn_a_moneyflow_ths_trade_days,
    )


@dg.sensor(
    job=raw_tushare_moneyflow_ths_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=MONEYFLOW_SENSOR_INTERVAL,
    required_resource_keys={"lake_root", "duckdb", "tushare"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    description=(
        f"{STOCK_THS_MONEYFLOW_AUTOMATION.register_start:%H:%M}后优先检查当日Raw源端覆盖，再查最近10日未完成日期；"
        f"缺失少于{STOCK_THS_MONEYFLOW_AUTOMATION.missing_record_limit}只才提交，已就绪不重复下载。"
    ),
)
def raw_tushare_moneyflow_ths_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return evaluate_stock_moneyflow_ths(context, datetime.now(CN_A_SENSOR_TIMEZONE))


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    monitored_jobs=[raw_tushare_moneyflow_ths_update_job],
    request_job=silver_moneyflow_ths_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=MONEYFLOW_SENSOR_INTERVAL,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="Raw任务完整成功后按本次日期和最终摘要接续Silver；同内容只自动提交一次，失败仅人工恢复，不扫描历史窗口。",
)
def silver_moneyflow_ths_update_job_sensor(
    context: dg.RunStatusSensorContext,
    lake_root: LakeRootResource,
) -> dg.RunRequest | dg.SkipReason:
    day = context.partition_key
    raw = context.instance.event_log_storage.get_records_for_run(
        context.dagster_run.run_id,
        of_type=dg.DagsterEventType.ASSET_MATERIALIZATION,
        limit=1, ascending=False,
    ).records[0]
    digest = raw.asset_materialization.metadata["goldenshare/file_sha256"].value
    records = context.instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=dg.AssetKey("silver_moneyflow_ths"), asset_partitions=[day]
        ), limit=1,
    )
    if records.records:
        silver = records.records[0]
        metadata = silver.asset_materialization.metadata
        consumed = metadata.get("goldenshare/raw_sha256")
        if consumed is not None and consumed.value == digest:
            checks = context.instance.event_log_storage.get_asset_check_execution_history(
                dg.AssetCheckKey(dg.AssetKey("silver_moneyflow_ths"), MONEYFLOW_THS_SILVER_CHECK),
                limit=1,
                status={AssetCheckExecutionRecordStatus.SUCCEEDED, AssetCheckExecutionRecordStatus.FAILED},
                partition_filter=PartitionKeyFilter(key=day),
            )
            if not checks:
                return dg.SkipReason(f"{day}同内容Silver缺少检查，需人工处理。")
            check = checks[0]
            evaluation = check.event.dagster_event.event_specific_data
            target = evaluation.target_materialization_data
            if not (
                check.status == AssetCheckExecutionRecordStatus.SUCCEEDED
                and evaluation.passed and evaluation.blocking and target is not None
                and target.storage_id == silver.storage_id
                and target.run_id == silver.run_id and target.timestamp == silver.timestamp
            ):
                return dg.SkipReason(f"{day}同内容Silver检查失败或不对应该次物化，需人工处理。")
            path = silver_moneyflow_path(lake_root.root(), "moneyflow_ths", day)
            expected = metadata.get("goldenshare/file_sha256")
            lake_root.ensure_available_for_run()
            if (
                expected is None or not isinstance(expected.value, str) or len(expected.value) != 64
                or not path.is_file() or any(p.is_symlink() for p in (path, *path.parents))
                or path.stat().st_size > MONEYFLOW_THS_READINESS_FILE_MAX_BYTES
                or candidate_file_hash(path) != expected.value
            ):
                return dg.SkipReason(f"{day}同内容Silver文件与物化摘要不符，需人工处理。")
            return dg.SkipReason(f"{day}Silver已成功处理该Raw内容。")
    return build_run_request(
        run_key=build_asset_update_run_key(
            subject="silver_moneyflow_ths", unit_id=day + ":" + digest
        ),
        partition_key=day,
    )
