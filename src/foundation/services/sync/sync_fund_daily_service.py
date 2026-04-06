from __future__ import annotations

from datetime import date

from src.foundation.config.settings import get_settings
from src.foundation.services.sync.fields import FUND_DAILY_FIELDS
from src.foundation.services.sync.resource_sync import HttpResourceSyncService
from src.utils import coerce_row


def build_fund_daily_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    settings = get_settings()
    if run_type == "FULL":
        params = {"start_date": kwargs.get("start_date", settings.history_start_date).replace("-", "")}
        if kwargs.get("end_date"):
            params["end_date"] = kwargs["end_date"].replace("-", "")
        return {k: v for k, v in params.items() if v}
    if trade_date is None:
        raise ValueError("trade_date is required for incremental fund_daily sync")
    params = {"trade_date": trade_date.strftime("%Y%m%d")}
    if kwargs.get("start_date"):
        params["start_date"] = kwargs["start_date"].replace("-", "")
    if kwargs.get("end_date"):
        params["end_date"] = kwargs["end_date"].replace("-", "")
    return params


class SyncFundDailyService(HttpResourceSyncService):
    job_name = "sync_fund_daily"
    target_table = "core.fund_daily_bar"
    api_name = "fund_daily"
    raw_dao_name = "raw_fund_daily"
    core_dao_name = "fund_daily_bar"
    fields = FUND_DAILY_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount")
    params_builder = staticmethod(build_fund_daily_params)
    core_transform = staticmethod(lambda row: {**row, "change_amount": row.get("change")})
    page_limit = 5000

    def execute(self, run_type: str, **kwargs):  # type: ignore[no-untyped-def]
        trade_date = kwargs.get("trade_date")
        if run_type == "INCREMENTAL" and trade_date is None:
            raise ValueError("trade_date is required for incremental fund_daily sync")

        base_params = self.params_builder(run_type, **kwargs)
        page_limit = int(kwargs.get("page_limit") or kwargs.get("limit") or self.page_limit)
        offset = int(kwargs.get("offset") or 0)

        raw_dao = getattr(self.dao, self.raw_dao_name)
        core_dao = getattr(self.dao, self.core_dao_name)

        fetched_total = 0
        written_total = 0
        while True:
            params = {**base_params, "limit": page_limit, "offset": offset}
            rows = self.client.call(self.api_name, params=params, fields=self.fields)
            if not rows:
                break
            normalized = [coerce_row(row, self.date_fields, self.decimal_fields) for row in rows]
            raw_dao.bulk_upsert(normalized)
            written_total += core_dao.bulk_upsert([self.core_transform(row) for row in normalized])
            fetched_total += len(rows)
            if len(rows) < page_limit:
                break
            offset += page_limit

        result_date = trade_date if isinstance(trade_date, date) else None
        return fetched_total, written_total, result_date, None
