"""Stopped by default; evaluation produces seven immutable window requests."""

import hashlib
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.anns_d_contract import ANNOUNCEMENT_ASSET
from orchestrator.defs.anns_d_window import (
    announcement_refresh_dates,
    announcement_window_tags,
)
from orchestrator.defs.jobs.anns_d import raw_anns_d_update_job
from orchestrator.defs.run_contracts.anns_d import (
    ANNOUNCEMENT_CRON,
    ANNOUNCEMENT_TIMEZONE,
    AnnouncementPolicy,
)
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key


@dg.schedule(
    job=raw_anns_d_update_job,
    cron_schedule=ANNOUNCEMENT_CRON,
    execution_timezone=ANNOUNCEMENT_TIMEZONE,
    default_status=dg.DefaultScheduleStatus.STOPPED,
    name="raw_anns_d_update_schedule",
)
def raw_anns_d_update_schedule(context: dg.ScheduleEvaluationContext):
    scheduled = context.scheduled_execution_time
    days = announcement_refresh_dates(scheduled)
    tick = scheduled.astimezone(ZoneInfo(ANNOUNCEMENT_TIMEZONE)).date().isoformat()
    window_id = hashlib.sha256(f"anns_d:{tick}".encode()).hexdigest()[:32]
    tags = announcement_window_tags(window_id, days[0], days[-1], scheduled.timestamp())
    for index, day in enumerate(days):
        yield dg.RunRequest(
            run_key=build_asset_update_run_key(
                subject="anns_d", unit_id=f"{tick}:{day}"
            ),
            partition_key=day,
            run_config={
                "ops": {
                    ANNOUNCEMENT_ASSET: {
                        "config": {
                            "interval_seconds": AnnouncementPolicy().interval_seconds
                        }
                    }
                }
            },
            tags={**tags, "dagster/priority": str(7 - index)},
        )
