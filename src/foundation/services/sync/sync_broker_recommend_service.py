from __future__ import annotations

from datetime import date, datetime

from src.foundation.services.sync.fields import BROKER_RECOMMEND_FIELDS
from src.foundation.services.sync.resource_sync import HttpResourceSyncService
from src.utils import coerce_row


def _normalize_month(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    if len(cleaned) == 7 and cleaned[4] == "-":
        cleaned = cleaned.replace("-", "")
    if len(cleaned) != 6 or not cleaned.isdigit():
        raise ValueError("month 必须是 YYYYMM 或 YYYY-MM 格式")
    return cleaned


def build_broker_recommend_params(run_type: str, trade_date: date | None = None, **kwargs):  # type: ignore[no-untyped-def]
    month = _normalize_month(kwargs.get("month"))
    if month is None and trade_date is not None:
        month = trade_date.strftime("%Y%m")
    if month is None and run_type == "INCREMENTAL":
        month = datetime.now().strftime("%Y%m")
    if month is None:
        return {}
    return {"month": month}


class SyncBrokerRecommendService(HttpResourceSyncService):
    job_name = "sync_broker_recommend"
    target_table = "core_serving.broker_recommend"
    api_name = "broker_recommend"
    raw_dao_name = "raw_broker_recommend"
    core_dao_name = "broker_recommend"
    fields = BROKER_RECOMMEND_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("close", "pct_change", "target_price")
    params_builder = staticmethod(build_broker_recommend_params)
    page_limit = 1000

    def execute(self, run_type: str, **kwargs):  # type: ignore[no-untyped-def]
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
            for row in normalized:
                row["offset"] = offset
            raw_dao.bulk_upsert(normalized)
            written_total += core_dao.bulk_upsert(normalized)
            fetched_total += len(rows)
            if len(rows) < page_limit:
                break
            offset += page_limit

        result_month = base_params.get("month")
        result_date = None
        if isinstance(result_month, str) and len(result_month) == 6 and result_month.isdigit():
            result_date = date(int(result_month[:4]), int(result_month[4:6]), 1)
        return fetched_total, written_total, result_date, None
