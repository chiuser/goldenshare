from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.foundation.dao.factory import DAOFactory
from src.foundation.models.core.equity_adj_factor import EquityAdjFactor
from src.foundation.models.core.equity_block_trade import EquityBlockTrade
from src.foundation.models.core.equity_daily_bar import EquityDailyBar
from src.foundation.models.core.equity_daily_basic import EquityDailyBasic
from src.foundation.models.core.equity_limit_list import EquityLimitList
from src.foundation.models.core.equity_moneyflow import EquityMoneyflow
from src.foundation.models.core.equity_top_list import EquityTopList
from src.foundation.models.core.fund_daily_bar import FundDailyBar
from src.foundation.models.core.fund_adj_factor import FundAdjFactor
from src.foundation.models.core.index_daily_bar import IndexDailyBar
from src.foundation.models.core.index_daily_serving import IndexDailyServing
from src.foundation.models.core.index_daily_basic import IndexDailyBasic
from src.foundation.models.core.index_monthly_bar import IndexMonthlyBar
from src.foundation.models.core.index_monthly_serving import IndexMonthlyServing
from src.foundation.models.core.index_weight import IndexWeight
from src.foundation.models.core.index_weekly_bar import IndexWeeklyBar
from src.foundation.models.core.index_weekly_serving import IndexWeeklyServing
from src.foundation.models.core.stk_period_bar import StkPeriodBar
from src.foundation.models.core.stk_period_bar_adj import StkPeriodBarAdj
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.ops.models.ops.sync_job_state import SyncJobState
from src.operations.specs import DatasetFreshnessSpec, get_dataset_freshness_spec, list_dataset_freshness_specs
from src.foundation.services.sync.registry import build_sync_service


OBSERVED_DATE_MODEL_REGISTRY: dict[str, type] = {
    "core.trade_calendar": TradeCalendar,
    "core.equity_daily_bar": EquityDailyBar,
    "core.equity_adj_factor": EquityAdjFactor,
    "core.equity_daily_basic": EquityDailyBasic,
    "core.equity_moneyflow": EquityMoneyflow,
    "core.equity_top_list": EquityTopList,
    "core.equity_block_trade": EquityBlockTrade,
    "core.equity_limit_list": EquityLimitList,
    "core.stk_period_bar": StkPeriodBar,
    "core.stk_period_bar_adj": StkPeriodBarAdj,
    "core.fund_daily_bar": FundDailyBar,
    "core.fund_adj_factor": FundAdjFactor,
    "core.index_daily_bar": IndexDailyBar,
    "core.index_daily_serving": IndexDailyServing,
    "core.index_weekly_bar": IndexWeeklyBar,
    "core.index_weekly_serving": IndexWeeklyServing,
    "core.index_monthly_bar": IndexMonthlyBar,
    "core.index_monthly_serving": IndexMonthlyServing,
    "core.index_daily_basic": IndexDailyBasic,
    "core.index_weight": IndexWeight,
}


@dataclass(slots=True)
class ReconciledSyncJobState:
    job_name: str
    resource_key: str
    display_name: str
    target_table: str
    previous_last_success_date: date | None
    observed_last_success_date: date


class SyncJobStateReconciliationService:
    def refresh_resource_state_from_observed(self, session: Session, resource_key: str) -> date | None:
        spec = get_dataset_freshness_spec(resource_key)
        if spec is None or spec.observed_date_column is None:
            return None
        observed_last_success_date = self._latest_observed_business_date(session, spec)
        if not isinstance(observed_last_success_date, date):
            return None

        sync_service = build_sync_service(resource_key, session)
        DAOFactory(session).sync_job_state.mark_success(
            sync_service.job_name,
            sync_service.target_table,
            observed_last_success_date,
        )
        session.commit()
        return observed_last_success_date

    def preview_stale_sync_job_states(self, session: Session) -> list[ReconciledSyncJobState]:
        items: list[ReconciledSyncJobState] = []
        for spec in list_dataset_freshness_specs():
            item = self._build_reconciliation_item(session, spec)
            if item is not None:
                items.append(item)
        items.sort(key=lambda item: (item.display_name, item.job_name))
        return items

    def reconcile_stale_sync_job_states(self, session: Session) -> list[ReconciledSyncJobState]:
        items = self.preview_stale_sync_job_states(session)
        dao = DAOFactory(session).sync_job_state
        for item in items:
            dao.reconcile_success_date(item.job_name, item.target_table, item.observed_last_success_date)
        session.commit()
        return items

    def _build_reconciliation_item(self, session: Session, spec: DatasetFreshnessSpec) -> ReconciledSyncJobState | None:
        if spec.observed_date_column is None:
            return None
        observed_last_success_date = self._latest_observed_business_date(session, spec)
        if not isinstance(observed_last_success_date, date):
            return None

        state = session.get(SyncJobState, spec.job_name)
        previous_last_success_date = state.last_success_date if state is not None else None
        if previous_last_success_date is not None and observed_last_success_date <= previous_last_success_date:
            return None

        return ReconciledSyncJobState(
            job_name=spec.job_name,
            resource_key=spec.resource_key,
            display_name=spec.display_name,
            target_table=spec.target_table,
            previous_last_success_date=previous_last_success_date,
            observed_last_success_date=observed_last_success_date,
        )

    @staticmethod
    def _latest_observed_business_date(session: Session, spec: DatasetFreshnessSpec) -> date | None:
        if spec.observed_date_column is None:
            return None
        model = OBSERVED_DATE_MODEL_REGISTRY.get(spec.target_table)
        if model is None:
            return None
        column = getattr(model, spec.observed_date_column, None)
        if column is None:
            return None
        try:
            return session.scalar(select(func.max(column)))
        except SQLAlchemyError:
            session.rollback()
            return None
