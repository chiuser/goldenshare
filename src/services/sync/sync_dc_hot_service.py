from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select

from src.clients.tushare_client import TushareHttpClient
from src.models.core.us_security import UsSecurity
from src.services.sync.base_sync_service import BaseSyncService
from src.services.sync.fields import DC_HOT_FIELDS
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
    # Keep first-seen order stable for deterministic request/query context expansion.
    deduped = list(dict.fromkeys(values))
    return deduped or [None]


def build_dc_hot_params(run_type: str, trade_date=None, **kwargs):  # type: ignore[no-untyped-def]
    if run_type == "FULL":
        params = {
            "trade_date": kwargs.get("trade_date"),
            "start_date": kwargs.get("start_date"),
            "end_date": kwargs.get("end_date"),
            "ts_code": kwargs.get("ts_code"),
            "market": kwargs.get("market"),
            "hot_type": kwargs.get("hot_type"),
            "is_new": kwargs.get("is_new"),
        }
        return {key: value.replace("-", "") if key in {"trade_date", "start_date", "end_date"} and isinstance(value, str) else value for key, value in params.items() if value}
    if trade_date is None:
        raise ValueError("trade_date is required for incremental dc_hot sync")
    params = {
        "trade_date": trade_date.strftime("%Y%m%d"),
        "ts_code": kwargs.get("ts_code"),
        "market": kwargs.get("market"),
        "hot_type": kwargs.get("hot_type"),
        "is_new": kwargs.get("is_new"),
    }
    return {key: value for key, value in params.items() if value}


class SyncDcHotService(BaseSyncService):
    job_name = "sync_dc_hot"
    target_table = "core.dc_hot"
    fields = DC_HOT_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("pct_change", "current_price", "hot")

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.client = TushareHttpClient()
        self._us_name_cache: dict[str, str | None] = {}

    def _lookup_us_ts_code_by_name(self, ts_name: str) -> str | None:
        normalized_name = ts_name.strip()
        if not normalized_name:
            return None
        if normalized_name in self._us_name_cache:
            return self._us_name_cache[normalized_name]

        matches = list(
            self.session.scalars(
                select(UsSecurity.ts_code).where(UsSecurity.name == normalized_name)
            )
        )
        resolved = matches[0] if len(matches) == 1 else None
        self._us_name_cache[normalized_name] = resolved
        if len(matches) > 1:
            self.logger.warning("skip dc_hot us ts_code enrichment for %s: multiple us_security matches", normalized_name)
        return resolved

    def _enrich_missing_us_ts_code(self, row: dict[str, Any]) -> bool:
        if row.get("ts_code") or row.get("query_market") != "美股市场":
            return True
        ts_name = row.get("ts_name")
        if not isinstance(ts_name, str) or not ts_name.strip():
            return False
        resolved_ts_code = self._lookup_us_ts_code_by_name(ts_name)
        if resolved_ts_code:
            row["ts_code"] = resolved_ts_code
            return True
        self.logger.warning("skip dc_hot us ts_code enrichment for %s: no unique us_security match", ts_name)
        return False

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        trade_date = kwargs.get("trade_date")
        extra_kwargs = {key: value for key, value in kwargs.items() if key != "trade_date"}
        total_fetched = 0
        total_written = 0
        unresolved_us_rows = 0
        for market in _normalize_filter_values(extra_kwargs.get("market")):
            for hot_type in _normalize_filter_values(extra_kwargs.get("hot_type")):
                for is_new in _normalize_filter_values(extra_kwargs.get("is_new")):
                    params_kwargs = dict(extra_kwargs)
                    params_kwargs["market"] = market
                    params_kwargs["hot_type"] = hot_type
                    params_kwargs["is_new"] = is_new
                    params = build_dc_hot_params(run_type, trade_date=trade_date, **params_kwargs)
                    rows = self.client.call("dc_hot", params=params, fields=self.fields)
                    normalized = [coerce_row(row, self.date_fields, self.decimal_fields) for row in rows]
                    for row in normalized:
                        row["query_market"] = params.get("market") or "__ALL__"
                        row["query_hot_type"] = params.get("hot_type") or "__ALL__"
                        row["query_is_new"] = params.get("is_new") or "__ALL__"
                        if row.get("query_market") == "美股市场" and not self._enrich_missing_us_ts_code(row):
                            unresolved_us_rows += 1
                    self.dao.raw_dc_hot.bulk_upsert(normalized)
                    total_written += self.dao.dc_hot.bulk_upsert(normalized)
                    total_fetched += len(rows)
        message = None
        if unresolved_us_rows:
            message = f"unresolved {unresolved_us_rows} dc_hot rows missing ts_code after us_security lookup"
        return total_fetched, total_written, trade_date, message
