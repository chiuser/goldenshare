from __future__ import annotations

from datetime import date, timedelta

from src.config.settings import get_settings
from src.services.sync.fields import TRADE_CAL_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService


def build_trade_cal_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    settings = get_settings()
    if run_type == "FULL":
        return {
            "exchange": kwargs.get("exchange", settings.default_exchange),
            "start_date": kwargs.get("start_date", settings.history_start_date).replace("-", ""),
            "end_date": kwargs.get("end_date"),
        }
    if trade_date is None:
        end = date.today()
        start = end - timedelta(days=30)
        return {
            "exchange": kwargs.get("exchange", settings.default_exchange),
            "start_date": start.strftime("%Y%m%d"),
            "end_date": end.strftime("%Y%m%d"),
        }
    text = trade_date.strftime("%Y%m%d")
    return {"exchange": kwargs.get("exchange", settings.default_exchange), "start_date": text, "end_date": text}


class SyncTradeCalendarService(HttpResourceSyncService):
    job_name = "sync_trade_calendar"
    target_table = "core.trade_calendar"
    api_name = "trade_cal"
    raw_dao_name = "raw_trade_cal"
    core_dao_name = "trade_calendar"
    fields = TRADE_CAL_FIELDS
    date_fields = ("cal_date", "pretrade_date")
    params_builder = staticmethod(build_trade_cal_params)
    core_transform = staticmethod(lambda row: {"exchange": row["exchange"], "trade_date": row["cal_date"], "is_open": bool(int(row["is_open"])) if isinstance(row["is_open"], str) else bool(row["is_open"]), "pretrade_date": row.get("pretrade_date")})
