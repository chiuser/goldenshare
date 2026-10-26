"""Stopped by default; refresh seven past days plus today and tomorrow."""

from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.anns_d_contract import ANNOUNCEMENT_ASSET, AnnouncementError
from orchestrator.defs.anns_d_window import (
    ANNOUNCEMENT_END_TAG,
    ANNOUNCEMENT_START_TAG,
    announcement_schedule_tags,
)
from orchestrator.defs.jobs.anns_d import raw_anns_d_update_job
from orchestrator.defs.run_contracts.anns_d import (
    ANNOUNCEMENT_CRON,
    ANNOUNCEMENT_EXECUTION_VERSION,
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
    if scheduled is None:
        raise AnnouncementError("announcement_schedule_time_missing")
    tags = announcement_schedule_tags(scheduled)
    tick = scheduled.astimezone(ZoneInfo(ANNOUNCEMENT_TIMEZONE)).date().isoformat()
    first, last = tags[ANNOUNCEMENT_START_TAG], tags[ANNOUNCEMENT_END_TAG]
    yield dg.RunRequest(
        run_key=build_asset_update_run_key(
            subject="anns_d",
            unit_id=f"update:{ANNOUNCEMENT_EXECUTION_VERSION}:{tick}:{first}:{last}",
        ),
        partition_key=None,
        run_config={
            "ops": {
                ANNOUNCEMENT_ASSET: {
                    "config": {
                        "interval_seconds": AnnouncementPolicy().interval_seconds
                    }
                }
            }
        },
        tags={
            **tags,
            "dagster/asset_partition_range_start": first,
            "dagster/asset_partition_range_end": last,
        },
    )
