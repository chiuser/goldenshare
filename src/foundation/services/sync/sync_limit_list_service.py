from __future__ import annotations

from datetime import date
from typing import Any

from src.foundation.services.sync.fields import LIMIT_LIST_FIELDS
from src.foundation.services.sync.resource_sync import HttpResourceSyncService
from src.utils import coerce_row

ALL_LIMIT_TYPES = ("U", "D", "Z")
ALL_EXCHANGES = ("SH", "SZ", "BJ")


def build_limit_list_params(run_type: str, trade_date: date | None = None, **kwargs):  # type: ignore[no-untyped-def]
    limit_type = kwargs.get("limit_type")
    exchange = kwargs.get("exchange")
    if run_type == "FULL":
        params = {
            "trade_date": kwargs.get("trade_date"),
            "start_date": kwargs.get("start_date"),
            "end_date": kwargs.get("end_date"),
            "ts_code": kwargs.get("ts_code"),
            "limit_type": limit_type,
            "exchange": exchange,
        }
        return {
            key: value.replace("-", "") if key in {"trade_date", "start_date", "end_date"} and isinstance(value, str) else value
            for key, value in params.items()
            if value
        }
    if trade_date is None:
        raise ValueError("trade_date is required for incremental limit_list_d sync")
    params = {
        "trade_date": trade_date.strftime("%Y%m%d"),
        "ts_code": kwargs.get("ts_code"),
        "limit_type": limit_type,
        "exchange": exchange,
    }
    return {key: value for key, value in params.items() if value}


class SyncLimitListService(HttpResourceSyncService):
    job_name = "sync_limit_list"
    target_table = "core_serving.equity_limit_list"
    api_name = "limit_list_d"
    raw_dao_name = "raw_limit_list"
    core_dao_name = "equity_limit_list"
    fields = LIMIT_LIST_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("close", "pct_chg", "amount", "limit_amount", "float_mv", "total_mv", "turnover_ratio", "fd_amount")
    params_builder = staticmethod(build_limit_list_params)
    core_transform = staticmethod(lambda row: {**row, "limit_type": row.get("limit")})

    @staticmethod
    def _normalize_enum_values(value: Any, defaults: tuple[str, ...]) -> tuple[str, ...]:
        if value is None:
            return defaults
        if isinstance(value, str):
            normalized = value.strip().upper()
            return (normalized,) if normalized else defaults
        if isinstance(value, (list, tuple, set)):
            values = tuple(str(item).strip().upper() for item in value if str(item).strip())
            return values if values else defaults
        normalized = str(value).strip().upper()
        return (normalized,) if normalized else defaults

    @staticmethod
    def _clean_date_value(value: Any) -> Any:
        if isinstance(value, date):
            return value.strftime("%Y%m%d")
        if isinstance(value, str):
            return value.replace("-", "")
        return value

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        trade_date = kwargs.get("trade_date")
        limit_types = self._normalize_enum_values(kwargs.get("limit_type"), ALL_LIMIT_TYPES)
        exchanges = self._normalize_enum_values(kwargs.get("exchange"), ALL_EXCHANGES)
        all_rows: list[dict[str, Any]] = []

        for limit_type in limit_types:
            for exchange in exchanges:
                call_params: dict[str, Any] = {
                    "trade_date": self._clean_date_value(kwargs.get("trade_date")),
                    "start_date": self._clean_date_value(kwargs.get("start_date")),
                    "end_date": self._clean_date_value(kwargs.get("end_date")),
                    "ts_code": kwargs.get("ts_code"),
                    "limit_type": limit_type,
                    "exchange": exchange,
                }
                request_params = {key: value for key, value in call_params.items() if value}
                rows = self.client.call(self.api_name, params=request_params, fields=self.fields)
                all_rows.extend(rows)

        normalized = [coerce_row(row, self.date_fields, self.decimal_fields) for row in all_rows]
        raw_dao = getattr(self.dao, self.raw_dao_name)
        core_dao = getattr(self.dao, self.core_dao_name)
        raw_dao.bulk_upsert(normalized)
        written = core_dao.bulk_upsert([self.core_transform(row) for row in normalized])
        return len(all_rows), written, trade_date, None
