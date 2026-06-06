import dagster as dg

from orchestrator.defs.jobs.lake_root_health_check import lake_root_health_check_job


lake_root_health_schedule = dg.ScheduleDefinition(
    job=lake_root_health_check_job,
    cron_schedule="0 */2 * * *",
    execution_timezone="Asia/Shanghai",
    default_status=dg.DefaultScheduleStatus.STOPPED,
    description="每两小时检查一次 lake root 基础设施健康状态。",
)
