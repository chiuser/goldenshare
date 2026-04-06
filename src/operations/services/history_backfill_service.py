from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from src.foundation.config.settings import get_settings
from src.foundation.dao.factory import DAOFactory
from src.foundation.services.sync.registry import build_sync_service
from src.operations.services.sync_job_state_reconciliation_service import SyncJobStateReconciliationService


@dataclass
class BackfillSummary:
    resource: str
    units_processed: int
    rows_fetched: int
    rows_written: int


class HistoryBackfillService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.dao = DAOFactory(session)
        self.settings = get_settings()
        self.sync_job_state_reconciliation = SyncJobStateReconciliationService()

    def backfill_trade_calendar(
        self,
        start_date: date,
        end_date: date,
        exchange: str | None = None,
        execution_id: int | None = None,
    ) -> BackfillSummary:
        service = build_sync_service("trade_cal", self.session)
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
        if resource == "stk_period_bar_week":
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
                service = build_sync_service(resource, self.session)
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
            service = build_sync_service(resource, self.session)
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
        limit_type: str | list[str] | None = None,
        ts_code: str | None = None,
        con_code: str | None = None,
        idx_type: str | None = None,
        market: str | list[str] | None = None,
        hot_type: str | list[str] | None = None,
        is_new: str | list[str] | None = None,
        offset: int = 0,
        limit: int | None = None,
        progress: Callable[[str], None] | None = None,
        execution_id: int | None = None,
    ) -> BackfillSummary:
        trade_date_resources = {
            "daily_basic",
            "moneyflow",
            "top_list",
            "block_trade",
            "limit_list_d",
            "dc_member",
            "ths_hot",
            "dc_hot",
            "limit_list_ths",
            "limit_step",
            "limit_cpt_list",
            "kpl_concept_cons",
        }
        if resource not in trade_date_resources:
            raise ValueError(
                "trade-date backfill only supports daily_basic, moneyflow, top_list, block_trade, limit_list_d, dc_member, ths_hot, dc_hot, limit_list_ths, limit_step, limit_cpt_list, and kpl_concept_cons"
            )
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
            service = build_sync_service(resource, self.session)
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
            service = build_sync_service(resource, self.session)
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
        if resource not in {"fund_daily"}:
            raise ValueError("fund series backfill only supports fund_daily")
        trade_dates = self.dao.trade_calendar.get_open_dates(self.settings.default_exchange, start_date, end_date)
        if offset:
            trade_dates = trade_dates[offset:]
        if limit is not None:
            trade_dates = trade_dates[:limit]
        rows_fetched = 0
        rows_written = 0
        total = len(trade_dates)
        for index, trade_date in enumerate(trade_dates, start=1):
            service = build_sync_service(resource, self.session)
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
                service = build_sync_service(resource, self.session)
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
                service = build_sync_service(resource, self.session)
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
            index_codes = self.dao.index_series_active.list_active_codes(resource)
            if resource == "index_daily_basic" and not index_codes:
                latest_open = self.dao.trade_calendar.get_latest_open_date(self.settings.default_exchange, end_date)
                if latest_open is not None:
                    discovery_service = build_sync_service(resource, self.session)
                    discovery_service.run_incremental(trade_date=latest_open, execution_id=execution_id)
                index_codes = self.dao.index_series_active.list_active_codes(resource)
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
            service = build_sync_service(resource, self.session)
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
    def _select_week_end_trade_dates(open_trade_dates: list[date]) -> list[date]:
        week_ends: dict[tuple[int, int], date] = {}
        for item in open_trade_dates:
            iso = item.isocalendar()
            key = (iso.year, iso.week)
            existing = week_ends.get(key)
            if existing is None or item > existing:
                week_ends[key] = item
        return [week_ends[key] for key in sorted(week_ends)]
