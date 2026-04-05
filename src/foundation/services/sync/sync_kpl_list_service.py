from __future__ import annotations

from datetime import date
from typing import Any

from src.foundation.config.settings import get_settings
from src.foundation.services.sync.fields import KPL_LIST_FIELDS
from src.foundation.services.sync.resource_sync import HttpResourceSyncService
from src.foundation.services.sync.sync_ths_hot_service import _normalize_filter_values
from src.utils import coerce_row


def build_kpl_list_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    settings = get_settings()
    if run_type == "FULL":
        params = {
            "ts_code": kwargs.get("ts_code"),
            "tag": kwargs.get("tag"),
            "trade_date": kwargs.get("trade_date"),
            "start_date": kwargs.get("start_date") or settings.history_start_date,
            "end_date": kwargs.get("end_date"),
        }
        return {key: value.replace("-", "") if key in {"trade_date", "start_date", "end_date"} and isinstance(value, str) else value for key, value in params.items() if value}
    if trade_date is None:
        raise ValueError("trade_date is required for incremental kpl_list sync")
    params = {
        "trade_date": trade_date.strftime("%Y%m%d"),
        "ts_code": kwargs.get("ts_code"),
        "tag": kwargs.get("tag"),
    }
    return {key: value for key, value in params.items() if value}


class SyncKplListService(HttpResourceSyncService):
    job_name = "sync_kpl_list"
    target_table = "core.kpl_list"
    api_name = "kpl_list"
    raw_dao_name = "raw_kpl_list"
    core_dao_name = "kpl_list"
    fields = KPL_LIST_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = (
        "net_change",
        "bid_amount",
        "bid_change",
        "bid_turnover",
        "lu_bid_vol",
        "pct_chg",
        "bid_pct_chg",
        "rt_pct_chg",
        "limit_order",
        "amount",
        "turnover_rate",
        "free_float",
        "lu_limit_order",
    )
    params_builder = staticmethod(build_kpl_list_params)

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        trade_date = kwargs.get("trade_date")
        extra_kwargs = {key: value for key, value in kwargs.items() if key != "trade_date"}
        total_fetched = 0
        total_written = 0
        for tag in _normalize_filter_values(extra_kwargs.get("tag")):
            params_kwargs = dict(extra_kwargs)
            params_kwargs["tag"] = tag
            params = build_kpl_list_params(run_type, trade_date=trade_date, **params_kwargs)
            rows = self.client.call(self.api_name, params=params, fields=self.fields)
            normalized = [coerce_row(row, self.date_fields, self.decimal_fields) for row in rows]
            self.dao.raw_kpl_list.bulk_upsert(normalized)
            total_written += self.dao.kpl_list.bulk_upsert(normalized)
            total_fetched += len(rows)
        return total_fetched, total_written, trade_date, None
