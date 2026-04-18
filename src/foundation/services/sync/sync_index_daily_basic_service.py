from __future__ import annotations

from datetime import date
from typing import Any

from src.foundation.config.settings import get_settings
from src.foundation.services.sync.fields import INDEX_DAILY_BASIC_FIELDS
from src.foundation.services.sync.resource_sync import HttpResourceSyncService
from src.utils import coerce_row


def build_index_daily_basic_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    params = {}
    if kwargs.get("ts_code"):
        params["ts_code"] = kwargs["ts_code"]
    if run_type == "FULL":
        if kwargs.get("start_date"):
            params["start_date"] = kwargs["start_date"].replace("-", "")
        if kwargs.get("end_date"):
            params["end_date"] = kwargs["end_date"].replace("-", "")
        if trade_date is not None:
            params["trade_date"] = trade_date.strftime("%Y%m%d")
        return params
    if trade_date is not None:
        params["trade_date"] = trade_date.strftime("%Y%m%d")
    if not params:
        raise ValueError("index_daily_basic sync requires ts_code or trade_date")
    return params


class SyncIndexDailyBasicService(HttpResourceSyncService):
    job_name = "sync_index_daily_basic"
    target_table = "core_serving.index_daily_basic"
    api_name = "index_dailybasic"
    raw_dao_name = "raw_index_daily_basic"
    core_dao_name = "index_daily_basic"
    fields = INDEX_DAILY_BASIC_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = (
        "total_mv",
        "float_mv",
        "total_share",
        "float_share",
        "free_share",
        "turnover_rate",
        "turnover_rate_f",
        "pe",
        "pe_ttm",
        "pb",
    )
    params_builder = staticmethod(build_index_daily_basic_params)
    resource_key = "index_daily_basic"
    page_limit = 1000

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        trade_date = kwargs.get("trade_date")
        execution_id = kwargs.get("execution_id")
        if trade_date is not None and self._is_closed_trade_date(trade_date):
            return 0, 0, trade_date, f"skip {self.resource_key} trade_date={trade_date.isoformat()} 非交易日"

        params_kwargs = {key: value for key, value in kwargs.items() if key != "trade_date"}
        params = self.params_builder(run_type, trade_date=trade_date, **params_kwargs)
        total_fetched = 0
        total_written = 0
        latest_seen_by_code: dict[str, date] = {}
        offset = 0
        while True:
            self.ensure_not_canceled(execution_id)
            page_params = {**params, "limit": self.page_limit, "offset": offset}
            rows = self.client.call(self.api_name, params=page_params, fields=self.fields)
            if not rows:
                break
            normalized = [coerce_row(row, self.date_fields, self.decimal_fields) for row in rows]
            raw_dao = getattr(self.dao, self.raw_dao_name)
            core_dao = getattr(self.dao, self.core_dao_name)
            raw_dao.bulk_upsert(normalized)
            written = core_dao.bulk_upsert(normalized)
            total_fetched += len(rows)
            total_written += written
            self._collect_latest_seen_dates(latest_seen_by_code, normalized)
            if len(rows) < self.page_limit:
                break
            offset += self.page_limit

        if latest_seen_by_code:
            self.index_series_active_store.upsert_seen_codes(self.resource_key, latest_seen_by_code)
        return total_fetched, total_written, trade_date, None

    @staticmethod
    def _collect_latest_seen_dates(latest_seen_by_code: dict[str, date], rows: list[dict[str, Any]]) -> None:
        for row in rows:
            ts_code = row.get("ts_code")
            seen_date = row.get("trade_date")
            if not ts_code or not isinstance(seen_date, date):
                continue
            previous = latest_seen_by_code.get(ts_code)
            if previous is None or seen_date > previous:
                latest_seen_by_code[ts_code] = seen_date

    def _is_closed_trade_date(self, trade_date: date) -> bool:
        exchange = get_settings().default_exchange
        row = self.dao.trade_calendar.fetch_by_pk(exchange, trade_date)
        return row is not None and not row.is_open
