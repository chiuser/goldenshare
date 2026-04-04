from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, or_, text, tuple_

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
    target_table = "core.index_weekly_serving"
    api_name = "index_weekly"
    raw_dao_name = "raw_index_weekly_bar"
    core_dao_name = "index_weekly_serving"
    fields = INDEX_WEEKLY_FIELDS
    date_fields = ("trade_date",)
    decimal_fields = ("open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount")
    params_builder = staticmethod(build_index_period_params("weekly"))
    core_transform = staticmethod(transform_index_period_bar)
    page_limit = 1000
    serving_table = "core.index_weekly_serving"
    period_kind = "weekly"

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        trade_date = kwargs.get("trade_date")
        execution_id = kwargs.get("execution_id")
        params = self.params_builder(run_type, **kwargs)
        target_codes = self._target_codes(kwargs.get("ts_code"))
        api_codes_seen: set[str] = set()

        total_fetched = 0
        total_written = 0
        offset = 0
        period_start_cache: dict[date, date] = {}
        while True:
            self.ensure_not_canceled(execution_id)
            page_params = {**params, "limit": self.page_limit, "offset": offset}
            rows = self.client.call(self.api_name, params=page_params, fields=self.fields)
            if not rows:
                break
            normalized = [coerce_row(row, self.date_fields, self.decimal_fields) for row in rows]
            filtered = [row for row in normalized if row.get("ts_code") in target_codes]
            raw_dao = getattr(self.dao, self.raw_dao_name)
            core_dao = getattr(self.dao, self.core_dao_name)
            raw_dao.bulk_upsert(normalized)
            serving_rows = [
                {
                    **self.core_transform(row),
                    "period_start_date": self._period_start_date(row["trade_date"], cache=period_start_cache),
                    "source": "api",
                }
                for row in filtered
            ]
            written = self._write_serving_rows(serving_rows, keep_api=False)
            api_codes_seen.update(row["ts_code"] for row in filtered if row.get("ts_code"))
            total_fetched += len(rows)
            total_written += written
            if len(rows) < self.page_limit:
                break
            offset += self.page_limit
        if trade_date is not None and kwargs.get("ts_code") is None:
            missing_codes = sorted(target_codes - api_codes_seen)
            total_written += self._fill_missing_from_daily(trade_date, missing_codes)
        return total_fetched, total_written, trade_date, None

    def _target_codes(self, ts_code: str | None) -> set[str]:
        active_codes = set(self.dao.index_series_active.list_active_codes("index_daily"))
        if ts_code:
            return {ts_code} if ts_code in active_codes else set()
        if active_codes:
            return active_codes
        return set()

    def _fill_missing_from_daily(self, trade_date: date, missing_codes: list[str]) -> int:
        if not missing_codes:
            return 0
        period_start_date = self._period_start_date(trade_date)
        start_date = period_start_date
        sql = text(
            f"""
            with win as (
                select
                    d.ts_code,
                    d.trade_date,
                    d.open,
                    d.high,
                    d.low,
                    d.close,
                    d.pre_close,
                    d.vol,
                    d.amount,
                    row_number() over (partition by d.ts_code order by d.trade_date asc) as rn_first,
                    row_number() over (partition by d.ts_code order by d.trade_date desc) as rn_last
                from core.index_daily_serving d
                where d.trade_date between :start_date and :trade_date
                  and d.ts_code = any(:missing_codes)
            ),
            agg as (
                select
                    ts_code,
                    max(case when rn_first = 1 then open end) as open,
                    max(high) as high,
                    min(low) as low,
                    max(case when rn_last = 1 then close end) as close,
                    max(case when rn_first = 1 then pre_close end) as pre_close,
                    sum(vol) as vol,
                    sum(amount) as amount
                from win
                group by ts_code
            )
            select
                a.ts_code,
                :period_start_date,
                :trade_date,
                a.open,
                a.high,
                a.low,
                a.close,
                a.pre_close,
                case when a.pre_close is null or a.close is null then null else a.close - a.pre_close end as change_amount,
                case
                    when a.pre_close is null or a.pre_close = 0 or a.close is null then null
                    else round(((a.close / a.pre_close) - 1) * 100, 4)
                end as pct_chg,
                a.vol,
                a.amount,
                'derived_daily'
            from agg a
            """
        )
        rows = self.session.execute(
            sql,
            {
                "trade_date": trade_date,
                "period_start_date": period_start_date,
                "start_date": start_date,
                "missing_codes": missing_codes,
            },
        ).mappings()
        serving_rows = [dict(row) for row in rows]
        return self._write_serving_rows(serving_rows, keep_api=True)

    def _write_serving_rows(self, rows: list[dict[str, Any]], *, keep_api: bool) -> int:
        if not rows:
            return 0
        deduped_rows = self._dedupe_by_period_key(rows)
        core_dao = getattr(self.dao, self.core_dao_name)
        model = core_dao.model
        period_keys = [(row["ts_code"], row["period_start_date"]) for row in deduped_rows]
        trade_keys = [(row["ts_code"], row["trade_date"]) for row in deduped_rows]
        stmt = delete(model).where(
            or_(
                tuple_(model.ts_code, model.period_start_date).in_(period_keys),
                tuple_(model.ts_code, model.trade_date).in_(trade_keys),
            )
        )
        if keep_api:
            stmt = stmt.where(model.source != "api")
        self.session.execute(stmt)
        return core_dao.bulk_insert(deduped_rows)

    @staticmethod
    def _dedupe_by_period_key(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped_by_key: dict[tuple[str, date], dict[str, Any]] = {}
        for row in rows:
            ts_code = row.get("ts_code")
            period_start_date = row.get("period_start_date")
            trade_date = row.get("trade_date")
            if not ts_code or period_start_date is None or trade_date is None:
                continue
            deduped_by_key[(ts_code, period_start_date)] = row
        return list(deduped_by_key.values())

    def _period_start_date(self, trade_date: date, *, cache: dict[date, date] | None = None) -> date:
        natural_start = self._natural_period_start_date(trade_date)
        if cache is not None and natural_start in cache:
            return cache[natural_start]
        exchange = get_settings().default_exchange
        open_dates = self.dao.trade_calendar.get_open_dates(exchange, natural_start, trade_date)
        period_start = open_dates[0] if open_dates else natural_start
        if cache is not None:
            cache[natural_start] = period_start
        return period_start

    def _natural_period_start_date(self, trade_date: date) -> date:
        if self.period_kind == "monthly":
            return trade_date.replace(day=1)
        return trade_date - timedelta(days=trade_date.weekday())
