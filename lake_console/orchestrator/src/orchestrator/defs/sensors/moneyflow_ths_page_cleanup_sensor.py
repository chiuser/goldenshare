"""Clean only the source pages of a fully successful THS stock Raw job."""

from pathlib import Path

import dagster as dg

from orchestrator.defs.io.moneyflow_ths_page_cleanup import cleanup_moneyflow_ths_pages
from orchestrator.defs.jobs.moneyflow_ths import raw_tushare_moneyflow_ths_update_job
from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    monitored_jobs=[raw_tushare_moneyflow_ths_update_job],
    default_status=dg.DefaultSensorStatus.STOPPED,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="同花顺个股Raw任务及文件检查完整成功后，仅清理该运行的分页JSON，保留收据和恢复文件。",
)
def raw_tushare_moneyflow_ths_page_cleanup_sensor(
    context: dg.RunStatusSensorContext,
) -> dg.SkipReason:
    records = context.instance.event_log_storage.get_records_for_run(
        context.dagster_run.run_id,
        of_type=dg.DagsterEventType.ASSET_CHECK_EVALUATION,
        limit=1,
        ascending=False,
    ).records
    raw_check = (
        records[0].event_log_entry.dagster_event.asset_check_evaluation_data
        if records
        else None
    )
    count, size = cleanup_moneyflow_ths_pages(
        staging_root=Path(DEFAULT_LAKE_STAGING_ROOT),
        run=context.dagster_run,
        raw_check=raw_check,
    )
    message = f"已清理该次成功Raw运行的{count}个分页JSON，共{size}字节；收据和恢复文件保留。"
    context.log.info(message)
    return dg.SkipReason(message)
