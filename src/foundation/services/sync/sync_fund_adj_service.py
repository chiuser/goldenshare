from __future__ import annotations

from datetime import date

from src.foundation.config.settings import get_settings
from src.foundation.services.sync.fields import FUND_ADJ_FIELDS
from src.foundation.services.sync.resource_sync import HttpResourceSyncService
from src.utils import coerce_row


def build_fund_adj_params(run_type: str, trade_date: date | None = None, **kwargs):  # type: ignore[no-untyped-def]
    settings = get_settings()
    if run_type == "FULL":
        params = {"start_date": kwargs.get("start_date", settings.history_start_date).replace("-", "")}
        if kwargs.get("end_date"):
            params["end_date"] = kwargs["end_date"].replace("-", "")
        return params
    if trade_date is None:
        raise ValueError("trade_date is required for incremental fund_adj sync")
    params = {"trade_date": trade_date.strftime("%Y%m%d")}
    if kwargs.get("start_date"):
        params["start_date"] = kwargs["start_date"].replace("-", "")
    if kwargs.get("end_date"):
        params["end_date"] = kwargs["end_date"].replace("-", "")
    return params


class SyncFundAdjService(HttpResourceSyncService):
    job_name = "sync_fund_adj"
    target_table = "core.fund_adj_factor"
    api_name = "fund_adj"
    raw_dao_name = "raw_fund_adj"
    core_dao_name = "fund_adj_factor"
    fields = FUND_ADJ_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("adj_factor",)
    params_builder = staticmethod(build_fund_adj_params)
    page_limit = 2000

    def execute(self, run_type: str, **kwargs):  # type: ignore[no-untyped-def]
        trade_date = kwargs.get("trade_date")
        if run_type == "INCREMENTAL" and trade_date is None:
            raise ValueError("trade_date is required for incremental fund_adj sync")

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
            written_total += core_dao.bulk_upsert(normalized)
            fetched_total += len(rows)
            if len(rows) < page_limit:
                break
            offset += page_limit

        result_date = trade_date if isinstance(trade_date, date) else None
        return fetched_total, written_total, result_date, None
