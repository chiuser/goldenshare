from datetime import datetime, time
from pathlib import Path

import dagster as dg

from orchestrator.defs.daily_data_audit.evidence import SHANGHAI
from orchestrator.defs.daily_data_audit.index_minute_audit import (
    daily_data_audit_index_minute_job,
    index_minute_audit_requests,
)
from orchestrator.defs.daily_data_audit.registry import read_calendar
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)


@dg.sensor(
    job=daily_data_audit_index_minute_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.PLATFORM_OBSERVABILITY,
        target_layer=SensorTargetLayer.PLATFORM,
        role=SensorRole.ASSET_UPDATE,
    ),
)
def daily_data_audit_index_minute_job_sensor(context: dg.SensorEvaluationContext):
    now = datetime.now(SHANGHAI)
    root = Path(DEFAULT_LAKE_ROOT)
    calendar = read_calendar(root, now.date())
    day = max(
        (day for day, opened in calendar.items()
         if opened and datetime.combine(day, time(15), SHANGHAI) <= now),
        default=None,
    )
    if day is None:
        return dg.SkipReason("没有适用的已收盘交易日")
    requests = index_minute_audit_requests(context.instance, day, now, root)
    return dg.SensorResult(run_requests=requests, skip_reason=None if requests else "尚无待审计的就绪产出")
