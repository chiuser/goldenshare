from __future__ import annotations

from datetime import date
from typing import Any

from src.config.settings import get_settings
from src.services.sync.fields import INDEX_DAILY_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService
from src.utils import coerce_row


def build_index_daily_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    settings = get_settings()
    if run_type == "FULL":
        params = {"ts_code": kwargs.get("ts_code"), "start_date": kwargs.get("start_date", settings.history_start_date).replace("-", "")}
        if kwargs.get("end_date"):
            params["end_date"] = kwargs["end_date"].replace("-", "")
        return {k: v for k, v in params.items() if v}
    if trade_date is None:
        raise ValueError("trade_date is required for incremental index_daily sync")
    params = {"trade_date": trade_date.strftime("%Y%m%d"), "ts_code": kwargs.get("ts_code")}
    return {k: v for k, v in params.items() if v}


class SyncIndexDailyService(HttpResourceSyncService):
    job_name = "sync_index_daily"
    target_table = "core.index_daily_bar"
    api_name = "index_daily"
    raw_dao_name = "raw_index_daily"
    core_dao_name = "index_daily_bar"
    fields = INDEX_DAILY_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount")
    params_builder = staticmethod(build_index_daily_params)
    core_transform = staticmethod(lambda row: {**row, "change_amount": row.get("change")})

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        trade_date = kwargs.get("trade_date")
        if kwargs.get("ts_code"):
            return super().execute(run_type, **kwargs)

        index_codes = [item.ts_code for item in self.dao.index_basic.get_active_indexes()]
        total_fetched = 0
        total_written = 0
        for index_code in index_codes:
            params_kwargs = {**kwargs, "ts_code": index_code}
            params = self.params_builder(run_type, **params_kwargs)
            rows = self.client.call(self.api_name, params=params, fields=self.fields)
            normalized = [coerce_row(row, self.date_fields, self.decimal_fields) for row in rows]
            self.dao.raw_index_daily.bulk_upsert(normalized)
            total_written += self.dao.index_daily_bar.bulk_upsert([self.core_transform(row) for row in normalized])
            total_fetched += len(rows)
        return total_fetched, total_written, trade_date, None
