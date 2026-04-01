from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from src.config.settings import get_settings
from src.dao.factory import DAOFactory
from src.operations.services import SyncJobStateReconciliationService
from src.services.sync.registry import build_sync_service


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
        exchange: str | None = None,
        ts_code: str | None = None,
        con_code: str | None = None,
        idx_type: str | None = None,
        offset: int = 0,
        limit: int | None = None,
        progress: Callable[[str], None] | None = None,
        execution_id: int | None = None,
    ) -> BackfillSummary:
        trade_date_resources = {
            "daily_basic",
            "moneyflow",
            "limit_list_d",
            "dc_member",
        }
        if resource not in trade_date_resources:
            raise ValueError(
                "trade-date backfill only supports daily_basic, moneyflow, limit_list_d, and dc_member"
            )
        exchange_name = exchange or self.settings.default_exchange
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
            if con_code:
                incremental_kwargs["con_code"] = con_code
            if idx_type:
                incremental_kwargs["idx_type"] = idx_type
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
        funds = sorted(self.dao.etf_basic.get_fund_daily_candidates(), key=lambda item: item.ts_code)
        if offset:
            funds = funds[offset:]
        if limit is not None:
            funds = funds[:limit]
        rows_fetched = 0
        rows_written = 0
        total = len(funds)
        for index, fund in enumerate(funds, start=1):
            service = build_sync_service(resource, self.session)
            result = service.run_full(
                ts_code=fund.ts_code,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                execution_id=execution_id,
            )
            rows_fetched += result.rows_fetched
            rows_written += result.rows_written
            if progress is not None:
                progress(
                    f"{resource}: {index}/{total} ts_code={fund.ts_code} "
                    f"fetched={result.rows_fetched} written={result.rows_written}"
                )
        self.sync_job_state_reconciliation.refresh_resource_state_from_observed(self.session, resource)
        return BackfillSummary(resource, len(funds), rows_fetched, rows_written)

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
        indexes = sorted(self.dao.index_basic.get_active_indexes(), key=lambda item: item.ts_code)
        if offset:
            indexes = indexes[offset:]
        if limit is not None:
            indexes = indexes[:limit]
        rows_fetched = 0
        rows_written = 0
        total = len(indexes)
        for index_number, index_item in enumerate(indexes, start=1):
            service = build_sync_service(resource, self.session)
            kwargs = {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            }
            code_label = "ts_code"
            if resource == "index_weight":
                kwargs["index_code"] = index_item.ts_code
                code_label = "index_code"
            else:
                kwargs["ts_code"] = index_item.ts_code
            kwargs["execution_id"] = execution_id
            result = service.run_full(**kwargs)
            rows_fetched += result.rows_fetched
            rows_written += result.rows_written
            if progress is not None:
                progress(
                    f"{resource}: {index_number}/{total} {code_label}={index_item.ts_code} "
                    f"fetched={result.rows_fetched} written={result.rows_written}"
                )
        self.sync_job_state_reconciliation.refresh_resource_state_from_observed(self.session, resource)
        return BackfillSummary(resource, len(indexes), rows_fetched, rows_written)
