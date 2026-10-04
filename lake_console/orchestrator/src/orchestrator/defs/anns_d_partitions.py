"""Announcement dates are natural days, independent of trading calendars."""

import dagster as dg

from orchestrator.defs.run_contracts.anns_d import ANNOUNCEMENT_TIMEZONE

anns_d_natural_days = dg.DailyPartitionsDefinition(
    start_date="2020-01-01", timezone=ANNOUNCEMENT_TIMEZONE
)
