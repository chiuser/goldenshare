from __future__ import annotations

from datetime import date
from typing import Any

from src.foundation.clients.tushare_client import TushareHttpClient
from src.foundation.services.sync.base_sync_service import BaseSyncService
from src.foundation.services.sync.fields import THS_HOT_FIELDS
from src.utils import coerce_row


def _normalize_filter_values(value: Any) -> list[str | None]:
    if value is None:
        return [None]
    if isinstance(value, (list, tuple, set)):
        values = [str(item).strip() for item in value if str(item).strip()]
    else:
        values = [item.strip() for item in str(value).split(",") if item.strip()]
    if not values:
        return [None]
    deduped = list(dict.fromkeys(values))
    return deduped or [None]


def build_ths_hot_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    if run_type == "FULL":
        params = {
            "trade_date": kwargs.get("trade_date"),
            "start_date": kwargs.get("start_date"),
            "end_date": kwargs.get("end_date"),
            "ts_code": kwargs.get("ts_code"),
            "market": kwargs.get("market"),
            "is_new": kwargs.get("is_new"),
        }
        return {key: value.replace("-", "") if key in {"trade_date", "start_date", "end_date"} and isinstance(value, str) else value for key, value in params.items() if value}
    if trade_date is None:
        raise ValueError("trade_date is required for incremental ths_hot sync")
    params = {
        "trade_date": trade_date.strftime("%Y%m%d"),
        "ts_code": kwargs.get("ts_code"),
        "market": kwargs.get("market"),
        "is_new": kwargs.get("is_new"),
    }
    return {key: value for key, value in params.items() if value}


class SyncThsHotService(BaseSyncService):
    job_name = "sync_ths_hot"
    target_table = "core.ths_hot"
    fields = THS_HOT_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("pct_change", "current_price", "hot")

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.client = TushareHttpClient()

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        trade_date = kwargs.get("trade_date")
        extra_kwargs = {key: value for key, value in kwargs.items() if key != "trade_date"}
        total_fetched = 0
        total_written = 0
        for market in _normalize_filter_values(extra_kwargs.get("market")):
            for is_new in _normalize_filter_values(extra_kwargs.get("is_new")):
                params_kwargs = dict(extra_kwargs)
                params_kwargs["market"] = market
                params_kwargs["is_new"] = is_new
                params = build_ths_hot_params(run_type, trade_date=trade_date, **params_kwargs)
                rows = self.client.call("ths_hot", params=params, fields=self.fields)
                normalized = [coerce_row(row, self.date_fields, self.decimal_fields) for row in rows]
                for row in normalized:
                    row["query_market"] = params.get("market") or "__ALL__"
                    row["query_is_new"] = params.get("is_new") or "__ALL__"
                self.dao.raw_ths_hot.bulk_upsert(normalized)
                total_written += self.dao.ths_hot.bulk_upsert(normalized)
                total_fetched += len(rows)
        return total_fetched, total_written, trade_date, None
