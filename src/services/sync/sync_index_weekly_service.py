from __future__ import annotations

from datetime import date
from typing import Any

from src.config.settings import get_settings
from src.services.sync.fields import INDEX_WEEKLY_FIELDS
from src.services.sync.resource_sync import HttpResourceSyncService
from src.utils import coerce_row


def build_index_period_params(api_freq: str):
    def _builder(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
        settings = get_settings()
        if run_type == "FULL":
            params = {
                "ts_code": kwargs.get("ts_code"),
                "start_date": kwargs.get("start_date", settings.history_start_date).replace("-", ""),
            }
            if kwargs.get("end_date"):
                params["end_date"] = kwargs["end_date"].replace("-", "")
            if trade_date is not None:
                params["trade_date"] = trade_date.strftime("%Y%m%d")
            return {key: value for key, value in params.items() if value}
        if trade_date is None:
            raise ValueError(f"trade_date is required for incremental index_{api_freq} sync")
        return {"trade_date": trade_date.strftime("%Y%m%d")}

    return _builder


def transform_index_period_bar(row: dict):  # type: ignore[no-untyped-def]
    return {**row, "change_amount": row.get("change")}


class SyncIndexWeeklyService(HttpResourceSyncService):
    job_name = "sync_index_weekly"
    target_table = "core.index_weekly_bar"
    api_name = "index_weekly"
    raw_dao_name = "raw_index_weekly_bar"
    core_dao_name = "index_weekly_bar"
    fields = INDEX_WEEKLY_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount")
    params_builder = staticmethod(build_index_period_params("weekly"))
    core_transform = staticmethod(transform_index_period_bar)
    page_limit = 1000

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        trade_date = kwargs.get("trade_date")
        execution_id = kwargs.get("execution_id")
        params = self.params_builder(run_type, **kwargs)
        valid_index_codes = self._valid_index_codes()

        total_fetched = 0
        total_written = 0
        offset = 0
        while True:
            self.ensure_not_canceled(execution_id)
            page_params = {**params, "limit": self.page_limit, "offset": offset}
            rows = self.client.call(self.api_name, params=page_params, fields=self.fields)
            if not rows:
                break
            normalized = [coerce_row(row, self.date_fields, self.decimal_fields) for row in rows]
            filtered = [row for row in normalized if row.get("ts_code") in valid_index_codes]
            raw_dao = getattr(self.dao, self.raw_dao_name)
            core_dao = getattr(self.dao, self.core_dao_name)
            raw_dao.bulk_upsert(filtered)
            written = core_dao.bulk_upsert([self.core_transform(row) for row in filtered])
            total_fetched += len(rows)
            total_written += written
            if len(rows) < self.page_limit:
                break
            offset += self.page_limit
        return total_fetched, total_written, trade_date, None

    def _valid_index_codes(self) -> set[str]:
        return {item.ts_code for item in self.dao.index_basic.get_active_indexes() if item.ts_code}
