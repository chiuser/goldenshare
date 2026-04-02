from __future__ import annotations

from datetime import date
from typing import Any

from src.clients.tushare_client import TushareHttpClient
from src.services.sync.base_sync_service import BaseSyncService
from src.services.sync.fields import DC_HOT_FIELDS
from src.utils import coerce_row


def build_dc_hot_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    if run_type == "FULL":
        params = {
            "trade_date": kwargs.get("trade_date"),
            "start_date": kwargs.get("start_date"),
            "end_date": kwargs.get("end_date"),
            "ts_code": kwargs.get("ts_code"),
            "market": kwargs.get("market"),
            "hot_type": kwargs.get("hot_type"),
            "is_new": kwargs.get("is_new"),
        }
        return {key: value.replace("-", "") if key in {"trade_date", "start_date", "end_date"} and isinstance(value, str) else value for key, value in params.items() if value}
    if trade_date is None:
        raise ValueError("trade_date is required for incremental dc_hot sync")
    params = {
        "trade_date": trade_date.strftime("%Y%m%d"),
        "ts_code": kwargs.get("ts_code"),
        "market": kwargs.get("market"),
        "hot_type": kwargs.get("hot_type"),
        "is_new": kwargs.get("is_new"),
    }
    return {key: value for key, value in params.items() if value}


class SyncDcHotService(BaseSyncService):
    job_name = "sync_dc_hot"
    target_table = "core.dc_hot"
    fields = DC_HOT_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("pct_change", "current_price", "hot")

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.client = TushareHttpClient()

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        trade_date = kwargs.get("trade_date")
        extra_kwargs = {key: value for key, value in kwargs.items() if key != "trade_date"}
        params = build_dc_hot_params(run_type, trade_date=trade_date, **extra_kwargs)
        rows = self.client.call("dc_hot", params=params, fields=self.fields)
        normalized = [coerce_row(row, self.date_fields, self.decimal_fields) for row in rows]
        for row in normalized:
            row["query_market"] = params.get("market") or "__ALL__"
            row["query_hot_type"] = params.get("hot_type") or "__ALL__"
            row["query_is_new"] = params.get("is_new") or "__ALL__"
        self.dao.raw_dc_hot.bulk_upsert(normalized)
        written = self.dao.dc_hot.bulk_upsert(normalized)
        return len(rows), written, trade_date, None
