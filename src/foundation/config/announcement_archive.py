"""Deployment capability and the single internal data-center budget source."""
from dataclasses import dataclass


@dataclass(frozen=True)
class DataCenterPolicy:
    query_days: int = 30
    page_size: int = 50
    history_size: int = 20
    result_size: int = 50
    company_limit: int = 20
    keyword_limit: int = 64
    title_limit: int = 200
    sql_seconds: float = 4
    api_seconds: float = 5
    poll_seconds: float = 2
    heartbeat_seconds: float = 5
    stale_seconds: float = 15
    ttl_seconds: float = 900
    catalog_check_seconds: float = 30
    control_poll_seconds: float = .5
    catalog_unit_seconds: float = 60


def announcements_enabled(settings):
    return (settings.app_env.strip().lower() in {'dev', 'local'}
            and settings.wealth_local_announcements_enabled)
