from __future__ import annotations

from datetime import date
from typing import Any

from src.foundation.clients.tushare_client import TushareHttpClient
from src.foundation.services.sync.base_sync_service import BaseSyncService
from src.foundation.services.sync.fields import LIMIT_LIST_THS_FIELDS
from src.foundation.services.sync.sync_ths_hot_service import _normalize_filter_values
from src.utils import coerce_row


def build_limit_list_ths_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    if run_type == "FULL":
        params = {
            "trade_date": kwargs.get("trade_date"),
            "start_date": kwargs.get("start_date"),
            "end_date": kwargs.get("end_date"),
            "ts_code": kwargs.get("ts_code"),
            "limit_type": kwargs.get("limit_type"),
            "market": kwargs.get("market"),
        }
        return {
            key: value.replace("-", "") if key in {"trade_date", "start_date", "end_date"} and isinstance(value, str) else value
            for key, value in params.items()
            if value
        }
    if trade_date is None:
        raise ValueError("trade_date is required for incremental limit_list_ths sync")
    params = {
        "trade_date": trade_date.strftime("%Y%m%d"),
        "ts_code": kwargs.get("ts_code"),
        "limit_type": kwargs.get("limit_type"),
        "market": kwargs.get("market"),
    }
    return {key: value for key, value in params.items() if value}


class SyncLimitListThsService(BaseSyncService):
    job_name = "sync_limit_list_ths"
    target_table = "core.limit_list_ths"
    fields = LIMIT_LIST_THS_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = (
        "price",
        "pct_chg",
        "limit_order",
        "limit_amount",
        "turnover_rate",
        "free_float",
        "lu_limit_order",
        "limit_up_suc_rate",
        "turnover",
        "rise_rate",
        "sum_float",
    )

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.client = TushareHttpClient()

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        trade_date = kwargs.get("trade_date")
        extra_kwargs = {key: value for key, value in kwargs.items() if key != "trade_date"}
        total_fetched = 0
        total_written = 0
        for limit_type in _normalize_filter_values(extra_kwargs.get("limit_type")):
            for market in _normalize_filter_values(extra_kwargs.get("market")):
                params_kwargs = dict(extra_kwargs)
                params_kwargs["limit_type"] = limit_type
                params_kwargs["market"] = market
                params = build_limit_list_ths_params(run_type, trade_date=trade_date, **params_kwargs)
                rows = self.client.call("limit_list_ths", params=params, fields=self.fields)
                normalized = [coerce_row(row, self.date_fields, self.decimal_fields) for row in rows]
                for row in normalized:
                    row["query_limit_type"] = params.get("limit_type") or "__ALL__"
                    row["query_market"] = params.get("market") or "__ALL__"
                self.dao.raw_limit_list_ths.bulk_upsert(normalized)
                total_written += self.dao.limit_list_ths.bulk_upsert(normalized)
                total_fetched += len(rows)
        return total_fetched, total_written, trade_date, None
