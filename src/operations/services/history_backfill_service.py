from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from datetime import date
from calendar import monthrange

from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.foundation.dao.factory import DAOFactory
from src.foundation.kernel.contracts.index_series_active_store import IndexSeriesActiveStore
from src.foundation.kernel.contracts.sync_state_store import SyncJobStateStore, SyncRunLogStore
from src.foundation.kernel.contracts.sync_execution_context import SyncExecutionContext
from src.foundation.services.sync.registry import build_sync_service, list_trade_date_backfill_resources
from src.ops.services.operations_sync_job_state_reconciliation_service import SyncJobStateReconciliationService


@dataclass
class BackfillSummary:
    resource: str
    units_processed: int
    rows_fetched: int
    rows_written: int


class HistoryBackfillService:
    def __init__(
        self,
        session: Session,
        execution_context: SyncExecutionContext | None = None,
        run_log_store: SyncRunLogStore | None = None,
        job_state_store: SyncJobStateStore | None = None,
        index_series_active_store: IndexSeriesActiveStore | None = None,
    ) -> None:
        self.session = session
        self.execution_context = execution_context
        self.run_log_store = run_log_store
        self.job_state_store = job_state_store
        self.dao = DAOFactory(session)
        self._index_series_active_store = index_series_active_store
        self.settings = get_settings()
        self.sync_job_state_reconciliation = SyncJobStateReconciliationService(job_state_store=job_state_store)

    @property
    def index_series_active_store(self):
        if self._index_series_active_store is not None:
            return self._index_series_active_store
        return self.dao.index_series_active

    def _build_sync_service(self, resource: str):
        if (
            self.execution_context is None
            and self.run_log_store is None
            and self.job_state_store is None
            and self._index_series_active_store is None
        ):
            return build_sync_service(resource, self.session)
        return build_sync_service(
            resource,
            self.session,
            execution_context=self.execution_context,
            run_log_store=self.run_log_store,
            job_state_store=self.job_state_store,
            index_series_active_store=self._index_series_active_store,
        )

    def backfill_trade_calendar(
        self,
        start_date: date,
        end_date: date,
        exchange: str | None = None,
        execution_id: int | None = None,
    ) -> BackfillSummary:
        service = self._build_sync_service("trade_cal")
        result = service.run_full(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            exchange=exchange or self.settings.default_exchange,
            execution_id=execution_id,
        )
        self.sync_job_state_reconciliation.refresh_resource_state_from_observed(self.session, "trade_cal")
        return BackfillSummary("trade_cal", 1, result.rows_fetched, result.rows_written)

    def backfill_equity_series(
        self,
        resource: str,
        start_date: date,
        end_date: date,
        offset: int = 0,
        limit: int | None = None,
        progress: Callable[[str], None] | None = None,
        execution_id: int | None = None,
    ) -> BackfillSummary:
        equity_series_resources = {
            "daily",
            "adj_factor",
            "stk_period_bar_week",
            "stk_period_bar_month",
            "stk_period_bar_adj_week",
            "stk_period_bar_adj_month",
        }
        if resource not in equity_series_resources:
            raise ValueError(
                "equity series backfill only supports daily, adj_factor, "
                "stk_period_bar_week, stk_period_bar_month, "
                "stk_period_bar_adj_week, and stk_period_bar_adj_month"
            )
        if resource in {"daily", "adj_factor"}:
            exchange_name = self.settings.default_exchange
            trade_dates = self.dao.trade_calendar.get_open_dates(exchange_name, start_date, end_date)
            if offset:
                trade_dates = trade_dates[offset:]
            if limit is not None:
                trade_dates = trade_dates[:limit]
            rows_fetched = 0
            rows_written = 0
            total = len(trade_dates)
            for index, trade_date in enumerate(trade_dates, start=1):
                service = self._build_sync_service(resource)
                result = service.run_incremental(
                    trade_date=trade_date,
                    execution_id=execution_id,
                )
                rows_fetched += result.rows_fetched
                rows_written += result.rows_written
                if progress is not None:
                    progress(
                        f"{resource}: {index}/{total} trade_date={trade_date.isoformat()} "
                        f"fetched={result.rows_fetched} written={result.rows_written}"
                    )
            self.sync_job_state_reconciliation.refresh_resource_state_from_observed(self.session, resource)
            return BackfillSummary(resource, len(trade_dates), rows_fetched, rows_written)

        if resource in {"stk_period_bar_week", "stk_period_bar_adj_week", "stk_period_bar_month", "stk_period_bar_adj_month"}:
            if resource in {"stk_period_bar_week", "stk_period_bar_adj_week"}:
                trade_dates = self._iter_week_friday_dates(start_date, end_date)
            else:
                trade_dates = self._iter_month_end_dates(start_date, end_date)
            if offset:
                trade_dates = trade_dates[offset:]
            if limit is not None:
                trade_dates = trade_dates[:limit]
            rows_fetched = 0
            rows_written = 0
            total = len(trade_dates)
            for index, trade_date in enumerate(trade_dates, start=1):
                service = self._build_sync_service(resource)
                result = service.run_incremental(
                    trade_date=trade_date,
                    execution_id=execution_id,
                )
                rows_fetched += result.rows_fetched
                rows_written += result.rows_written
                if progress is not None:
                    progress(
                        f"{resource}: {index}/{total} trade_date={trade_date.isoformat()} "
                        f"fetched={result.rows_fetched} written={result.rows_written}"
                    )
            self.sync_job_state_reconciliation.refresh_resource_state_from_observed(self.session, resource)
            return BackfillSummary(resource, len(trade_dates), rows_fetched, rows_written)

        securities = sorted(self.dao.security.get_active_equities(), key=lambda item: item.ts_code)
        if offset:
            securities = securities[offset:]
        if limit is not None:
            securities = securities[:limit]
        rows_fetched = 0
        rows_written = 0
        total = len(securities)
        for index, security in enumerate(securities, start=1):
            service = self._build_sync_service(resource)
            result = service.run_full(
                ts_code=security.ts_code,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                execution_id=execution_id,
            )
            rows_fetched += result.rows_fetched
            rows_written += result.rows_written
            if progress is not None:
                progress(
                    f"{resource}: {index}/{total} ts_code={security.ts_code} "
                    f"fetched={result.rows_fetched} written={result.rows_written}"
                )
        self.sync_job_state_reconciliation.refresh_resource_state_from_observed(self.session, resource)
        return BackfillSummary(resource, len(securities), rows_fetched, rows_written)

    def backfill_by_trade_dates(
        self,
        resource: str,
        start_date: date,
        end_date: date,
        exchange: str | list[str] | None = None,
        exchange_id: str | list[str] | None = None,
        limit_type: str | list[str] | None = None,
        ts_code: str | None = None,
        con_code: str | None = None,
        idx_type: str | None = None,
        market: str | list[str] | None = None,
        hot_type: str | list[str] | None = None,
        is_new: str | list[str] | None = None,
        suspend_type: str | None = None,
        content_type: str | list[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
        progress: Callable[[str], None] | None = None,
        execution_id: int | None = None,
    ) -> BackfillSummary:
        trade_date_resources = list_trade_date_backfill_resources()
        trade_date_resource_set = set(trade_date_resources)
        if resource not in trade_date_resource_set:
            raise ValueError(f"trade-date backfill only supports {', '.join(trade_date_resources)}")
        exchange_name = self.settings.default_exchange if resource == "limit_list_d" else (exchange or self.settings.default_exchange)
        trade_dates = self.dao.trade_calendar.get_open_dates(exchange_name, start_date, end_date)
        if offset:
            trade_dates = trade_dates[offset:]
        if limit is not None:
            trade_dates = trade_dates[:limit]
        rows_fetched = 0
        rows_written = 0
        total = len(trade_dates)
        for index, trade_date in enumerate(trade_dates, start=1):
            service = self._build_sync_service(resource)
            incremental_kwargs = {
                "trade_date": trade_date,
                "execution_id": execution_id,
            }
            if ts_code:
                incremental_kwargs["ts_code"] = ts_code
            if limit_type:
                incremental_kwargs["limit_type"] = limit_type
            if exchange and resource == "limit_list_d":
                incremental_kwargs["exchange"] = exchange
            if exchange_id and resource == "margin":
                incremental_kwargs["exchange_id"] = exchange_id
            if con_code:
                incremental_kwargs["con_code"] = con_code
            if idx_type:
                incremental_kwargs["idx_type"] = idx_type
            if market:
                incremental_kwargs["market"] = market
            if hot_type:
                incremental_kwargs["hot_type"] = hot_type
            if is_new:
                incremental_kwargs["is_new"] = is_new
            if suspend_type:
                incremental_kwargs["suspend_type"] = suspend_type
            if content_type and resource == "moneyflow_ind_dc":
                incremental_kwargs["content_type"] = content_type
            result = service.run_incremental(
                **incremental_kwargs,
            )
            rows_fetched += result.rows_fetched
            rows_written += result.rows_written
            if progress is not None:
                progress(
                    f"{resource}: {index}/{total} trade_date={trade_date.isoformat()} "
                    f"fetched={result.rows_fetched} written={result.rows_written}"
                )
        self.sync_job_state_reconciliation.refresh_resource_state_from_observed(self.session, resource)
        return BackfillSummary(resource, len(trade_dates), rows_fetched, rows_written)

    def backfill_low_frequency_by_security(
        self,
        resource: str,
        offset: int = 0,
        limit: int | None = None,
        progress: Callable[[str], None] | None = None,
        execution_id: int | None = None,
    ) -> BackfillSummary:
        if resource not in {"dividend", "stk_holdernumber"}:
            raise ValueError("low-frequency backfill only supports dividend and stk_holdernumber")
        securities = sorted(self.dao.security.get_active_equities(), key=lambda item: item.ts_code)
        if offset:
            securities = securities[offset:]
        if limit is not None:
            securities = securities[:limit]
        rows_fetched = 0
        rows_written = 0
        total = len(securities)
        for index, security in enumerate(securities, start=1):
            service = self._build_sync_service(resource)
            result = service.run_full(ts_code=security.ts_code, execution_id=execution_id)
            rows_fetched += result.rows_fetched
            rows_written += result.rows_written
            if progress is not None:
                progress(
                    f"{resource}: {index}/{total} ts_code={security.ts_code} "
                    f"fetched={result.rows_fetched} written={result.rows_written}"
                )
        return BackfillSummary(resource, len(securities), rows_fetched, rows_written)

    def backfill_fund_series(
        self,
        resource: str,
        start_date: date,
        end_date: date,
        offset: int = 0,
        limit: int | None = None,
        progress: Callable[[str], None] | None = None,
        execution_id: int | None = None,
    ) -> BackfillSummary:
        if resource not in {"fund_daily", "fund_adj"}:
            raise ValueError("fund series backfill only supports fund_daily and fund_adj")
        trade_dates = self.dao.trade_calendar.get_open_dates(self.settings.default_exchange, start_date, end_date)
        if offset:
            trade_dates = trade_dates[offset:]
        if limit is not None:
            trade_dates = trade_dates[:limit]
        rows_fetched = 0
        rows_written = 0
        total = len(trade_dates)
        for index, trade_date in enumerate(trade_dates, start=1):
            service = self._build_sync_service(resource)
            result = service.run_incremental(
                trade_date=trade_date,
                execution_id=execution_id,
            )
            rows_fetched += result.rows_fetched
            rows_written += result.rows_written
            if progress is not None:
                progress(
                    f"{resource}: {index}/{total} trade_date={trade_date.isoformat()} "
                    f"fetched={result.rows_fetched} written={result.rows_written}"
                )
        self.sync_job_state_reconciliation.refresh_resource_state_from_observed(self.session, resource)
        return BackfillSummary(resource, len(trade_dates), rows_fetched, rows_written)

    def backfill_index_series(
        self,
        resource: str,
        start_date: date,
        end_date: date,
        offset: int = 0,
        limit: int | None = None,
        progress: Callable[[str], None] | None = None,
        execution_id: int | None = None,
    ) -> BackfillSummary:
        supported_resources = {
            "index_daily",
            "index_weekly",
            "index_monthly",
            "index_daily_basic",
            "index_weight",
        }
        if resource not in supported_resources:
            raise ValueError(
                "index series backfill only supports index_daily, index_weekly, index_monthly, index_daily_basic, and index_weight"
            )
        if resource == "index_weekly":
            open_trade_dates = self.dao.trade_calendar.get_open_dates(self.settings.default_exchange, start_date, end_date)
            trade_dates = self._select_week_end_trade_dates(open_trade_dates)
            if offset:
                trade_dates = trade_dates[offset:]
            if limit is not None:
                trade_dates = trade_dates[:limit]
            rows_fetched = 0
            rows_written = 0
            total = len(trade_dates)
            for index, trade_date in enumerate(trade_dates, start=1):
                service = self._build_sync_service(resource)
                result = service.run_incremental(trade_date=trade_date, execution_id=execution_id)
                rows_fetched += result.rows_fetched
                rows_written += result.rows_written
                if progress is not None:
                    progress(
                        f"{resource}: {index}/{total} trade_date={trade_date.isoformat()} "
                        f"fetched={result.rows_fetched} written={result.rows_written}"
                    )
            self.sync_job_state_reconciliation.refresh_resource_state_from_observed(self.session, resource)
            return BackfillSummary(resource, len(trade_dates), rows_fetched, rows_written)

        if resource == "index_monthly":
            open_trade_dates = self.dao.trade_calendar.get_open_dates(self.settings.default_exchange, start_date, end_date)
            trade_dates = self._select_month_end_trade_dates(open_trade_dates)
            if offset:
                trade_dates = trade_dates[offset:]
            if limit is not None:
                trade_dates = trade_dates[:limit]
            rows_fetched = 0
            rows_written = 0
            total = len(trade_dates)
            for index, trade_date in enumerate(trade_dates, start=1):
                service = self._build_sync_service(resource)
                result = service.run_incremental(trade_date=trade_date, execution_id=execution_id)
                rows_fetched += result.rows_fetched
                rows_written += result.rows_written
                if progress is not None:
                    progress(
                        f"{resource}: {index}/{total} trade_date={trade_date.isoformat()} "
                        f"fetched={result.rows_fetched} written={result.rows_written}"
                    )
            self.sync_job_state_reconciliation.refresh_resource_state_from_observed(self.session, resource)
            return BackfillSummary(resource, len(trade_dates), rows_fetched, rows_written)

        if resource in {"index_daily", "index_daily_basic"}:
            index_codes = self.index_series_active_store.list_active_codes(resource)
            if resource == "index_daily_basic" and not index_codes:
                latest_open = self.dao.trade_calendar.get_latest_open_date(self.settings.default_exchange, end_date)
                if latest_open is not None:
                    discovery_service = self._build_sync_service(resource)
                    discovery_service.run_incremental(trade_date=latest_open, execution_id=execution_id)
                index_codes = self.index_series_active_store.list_active_codes(resource)
        else:
            indexes = sorted(self.dao.index_basic.get_active_indexes(), key=lambda item: item.ts_code)
            index_codes = [item.ts_code for item in indexes if item.ts_code]
        if not index_codes:
            return BackfillSummary(resource, 0, 0, 0)
        if offset:
            index_codes = index_codes[offset:]
        if limit is not None:
            index_codes = index_codes[:limit]
        rows_fetched = 0
        rows_written = 0
        total = len(index_codes)
        for index_number, index_code in enumerate(index_codes, start=1):
            service = self._build_sync_service(resource)
            kwargs = {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            }
            code_label = "ts_code"
            if resource == "index_weight":
                kwargs["index_code"] = index_code
                code_label = "index_code"
            else:
                kwargs["ts_code"] = index_code
            if resource == "index_daily":
                kwargs["suppress_single_code_progress"] = True
            kwargs["execution_id"] = execution_id
            result = service.run_full(**kwargs)
            rows_fetched += result.rows_fetched
            rows_written += result.rows_written
            if progress is not None:
                progress(
                    f"{resource}: {index_number}/{total} {code_label}={index_code} "
                    f"fetched={result.rows_fetched} written={result.rows_written}"
                )
        self.sync_job_state_reconciliation.refresh_resource_state_from_observed(self.session, resource)
        return BackfillSummary(resource, len(index_codes), rows_fetched, rows_written)

    def backfill_by_months(
        self,
        resource: str,
        start_month: str,
        end_month: str,
        offset: int = 0,
        limit: int | None = None,
        progress: Callable[[str], None] | None = None,
        execution_id: int | None = None,
    ) -> BackfillSummary:
        if resource not in {"broker_recommend"}:
            raise ValueError("month backfill only supports broker_recommend")

        months = self._iter_months(start_month, end_month)
        if offset:
            months = months[offset:]
        if limit is not None:
            months = months[:limit]

        rows_fetched = 0
        rows_written = 0
        total = len(months)
        for index, month in enumerate(months, start=1):
            service = self._build_sync_service(resource)
            result = service.run_full(month=month, execution_id=execution_id)
            rows_fetched += result.rows_fetched
            rows_written += result.rows_written
            if progress is not None:
                progress(
                    f"{resource}: {index}/{total} month={month} "
                    f"fetched={result.rows_fetched} written={result.rows_written}"
                )
        self.sync_job_state_reconciliation.refresh_resource_state_from_observed(self.session, resource)
        return BackfillSummary(resource, len(months), rows_fetched, rows_written)

    @staticmethod
    def _select_month_end_trade_dates(open_trade_dates: list[date]) -> list[date]:
        month_ends: dict[tuple[int, int], date] = {}
        for item in open_trade_dates:
            key = (item.year, item.month)
            existing = month_ends.get(key)
            if existing is None or item > existing:
                month_ends[key] = item
        return [month_ends[key] for key in sorted(month_ends)]

    @staticmethod
    def _normalize_month(value: str) -> tuple[int, int]:
        cleaned = value.strip()
        if len(cleaned) == 7 and cleaned[4] == "-":
            cleaned = cleaned.replace("-", "")
        if len(cleaned) != 6 or not cleaned.isdigit():
            raise ValueError("月份格式错误，请使用 YYYY-MM 或 YYYYMM")
        year = int(cleaned[:4])
        month = int(cleaned[4:6])
        if month < 1 or month > 12:
            raise ValueError("月份格式错误，请使用 YYYY-MM 或 YYYYMM")
        return year, month

    @classmethod
    def _iter_months(cls, start_month: str, end_month: str) -> list[str]:
        start_year, start_month_value = cls._normalize_month(start_month)
        end_year, end_month_value = cls._normalize_month(end_month)
        start_code = start_year * 100 + start_month_value
        end_code = end_year * 100 + end_month_value
        if start_code > end_code:
            raise ValueError("开始月份不能晚于结束月份")

        months: list[str] = []
        year = start_year
        month = start_month_value
        while year * 100 + month <= end_code:
            months.append(f"{year:04d}{month:02d}")
            month += 1
            if month > 12:
                year += 1
                month = 1
        return months

    @staticmethod
    def _select_week_end_trade_dates(open_trade_dates: list[date]) -> list[date]:
        week_ends: dict[tuple[int, int], date] = {}
        for item in open_trade_dates:
            iso = item.isocalendar()
            key = (iso.year, iso.week)
            existing = week_ends.get(key)
            if existing is None or item > existing:
                week_ends[key] = item
        return [week_ends[key] for key in sorted(week_ends)]

    @staticmethod
    def _iter_week_friday_dates(start_date: date, end_date: date) -> list[date]:
        if start_date > end_date:
            return []
        days_until_friday = (4 - start_date.weekday()) % 7
        first_friday = start_date + timedelta(days=days_until_friday)
        dates: list[date] = []
        current = first_friday
        while current <= end_date:
            dates.append(current)
            current += timedelta(days=7)
        return dates

    @staticmethod
    def _iter_month_end_dates(start_date: date, end_date: date) -> list[date]:
        if start_date > end_date:
            return []
        dates: list[date] = []
        current = date(start_date.year, start_date.month, 1)
        while current <= end_date:
            last_day = monthrange(current.year, current.month)[1]
            month_end = date(current.year, current.month, last_day)
            if start_date <= month_end <= end_date:
                dates.append(month_end)
            if current.month == 12:
                current = date(current.year + 1, 1, 1)
            else:
                current = date(current.year, current.month + 1, 1)
        return dates
