from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from src.foundation.models.core.board_moneyflow_dc import BoardMoneyflowDc
from src.foundation.models.core.concept_moneyflow_ths import ConceptMoneyflowThs
from src.foundation.models.core.dc_member import DcMember
from src.foundation.models.core.equity_block_trade import EquityBlockTrade
from src.foundation.models.core.equity_cyq_perf import EquityCyqPerf
from src.foundation.models.core.equity_moneyflow import EquityMoneyflow
from src.foundation.models.core.equity_nineturn import EquityNineTurn
from src.foundation.models.core.equity_stock_st import EquityStockSt
from src.foundation.models.core.equity_top_list import EquityTopList
from src.foundation.models.core_serving.equity_daily_basic import EquityDailyBasic
from src.foundation.models.core.industry_moneyflow_ths import IndustryMoneyflowThs
from src.foundation.models.core.equity_margin import EquityMargin
from src.foundation.models.core.limit_cpt_list import LimitCptList
from src.foundation.models.core.limit_step import LimitStep
from src.foundation.models.core.market_moneyflow_dc import MarketMoneyflowDc
from src.foundation.models.core.equity_suspend_d import EquitySuspendD
from src.foundation.models.core.equity_stk_limit import EquityStkLimit
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.raw.raw_daily_basic import RawDailyBasic
from src.foundation.models.raw.raw_cyq_perf import RawCyqPerf
from src.foundation.models.raw.raw_margin import RawMargin
from src.foundation.models.raw.raw_limit_cpt_list import RawLimitCptList
from src.foundation.models.raw.raw_limit_step import RawLimitStep
from src.foundation.models.raw.raw_moneyflow import RawMoneyflow
from src.foundation.models.raw.raw_moneyflow_cnt_ths import RawMoneyflowCntThs
from src.foundation.models.raw.raw_moneyflow_dc import RawMoneyflowDc
from src.foundation.models.raw.raw_moneyflow_ind_dc import RawMoneyflowIndDc
from src.foundation.models.raw.raw_moneyflow_ind_ths import RawMoneyflowIndThs
from src.foundation.models.raw.raw_moneyflow_mkt_dc import RawMoneyflowMktDc
from src.foundation.models.raw.raw_moneyflow_ths import RawMoneyflowThs
from src.foundation.models.raw.raw_block_trade import RawBlockTrade
from src.foundation.models.raw.raw_dc_member import RawDcMember
from src.foundation.models.raw.raw_stock_st import RawStockSt
from src.foundation.models.raw.raw_stk_nineturn import RawStkNineTurn
from src.foundation.models.raw.raw_suspend_d import RawSuspendD
from src.foundation.models.raw.raw_stk_limit import RawStkLimit
from src.foundation.models.raw.raw_top_list import RawTopList
from src.foundation.models.raw.raw_trade_cal import RawTradeCal
from src.foundation.models.core.equity_moneyflow_dc import EquityMoneyflowDc
from src.foundation.models.core.equity_moneyflow_ths import EquityMoneyflowThs


@dataclass(slots=True, frozen=True)
class DatasetReconcileDailyDiff:
    trade_date: date
    raw_rows: int
    serving_rows: int
    diff: int


@dataclass(slots=True, frozen=True)
class DatasetReconcileReport:
    dataset_key: str
    start_date: date
    end_date: date
    raw_rows: int
    serving_rows: int
    daily_diffs: list[DatasetReconcileDailyDiff] = field(default_factory=list)

    @property
    def abs_diff(self) -> int:
        return abs(self.raw_rows - self.serving_rows)


class DatasetReconcileService:
    SUPPORTED_DATASETS: dict[str, tuple[type, str, type, str]] = {
        "trade_cal": (RawTradeCal, "cal_date", TradeCalendar, "trade_date"),
        "daily_basic": (RawDailyBasic, "trade_date", EquityDailyBasic, "trade_date"),
        "cyq_perf": (RawCyqPerf, "trade_date", EquityCyqPerf, "trade_date"),
        "stk_limit": (RawStkLimit, "trade_date", EquityStkLimit, "trade_date"),
        "suspend_d": (RawSuspendD, "trade_date", EquitySuspendD, "trade_date"),
        "margin": (RawMargin, "trade_date", EquityMargin, "trade_date"),
        "limit_step": (RawLimitStep, "trade_date", LimitStep, "trade_date"),
        "limit_cpt_list": (RawLimitCptList, "trade_date", LimitCptList, "trade_date"),
        "moneyflow": (RawMoneyflow, "trade_date", EquityMoneyflow, "trade_date"),
        "moneyflow_ths": (RawMoneyflowThs, "trade_date", EquityMoneyflowThs, "trade_date"),
        "moneyflow_dc": (RawMoneyflowDc, "trade_date", EquityMoneyflowDc, "trade_date"),
        "moneyflow_cnt_ths": (RawMoneyflowCntThs, "trade_date", ConceptMoneyflowThs, "trade_date"),
        "moneyflow_ind_ths": (RawMoneyflowIndThs, "trade_date", IndustryMoneyflowThs, "trade_date"),
        "moneyflow_ind_dc": (RawMoneyflowIndDc, "trade_date", BoardMoneyflowDc, "trade_date"),
        "moneyflow_mkt_dc": (RawMoneyflowMktDc, "trade_date", MarketMoneyflowDc, "trade_date"),
        "top_list": (RawTopList, "trade_date", EquityTopList, "trade_date"),
        "block_trade": (RawBlockTrade, "trade_date", EquityBlockTrade, "trade_date"),
        "stock_st": (RawStockSt, "trade_date", EquityStockSt, "trade_date"),
        "stk_nineturn": (RawStkNineTurn, "trade_date", EquityNineTurn, "trade_date"),
        "dc_member": (RawDcMember, "trade_date", DcMember, "trade_date"),
    }

    def run(
        self,
        session: Session,
        *,
        dataset_key: str,
        start_date: date | None = None,
        end_date: date | None = None,
        sample_limit: int = 20,
    ) -> DatasetReconcileReport:
        config = self.SUPPORTED_DATASETS.get(dataset_key)
        if config is None:
            supported = ", ".join(sorted(self.SUPPORTED_DATASETS.keys()))
            raise ValueError(f"dataset={dataset_key} is not supported. supported={supported}")
        raw_model, raw_date_field, serving_model, serving_date_field = config

        resolved_end = end_date or date.today()
        resolved_start = start_date or (resolved_end - timedelta(days=7))
        if resolved_start > resolved_end:
            raise ValueError("start_date must be <= end_date")

        raw_date_col = getattr(raw_model, raw_date_field)
        serving_date_col = getattr(serving_model, serving_date_field)

        raw_rows = self._count_rows(
            session,
            stmt=select(func.count()).select_from(raw_model).where(raw_date_col >= resolved_start, raw_date_col <= resolved_end),
        )
        serving_rows = self._count_rows(
            session,
            stmt=select(func.count()).select_from(serving_model).where(serving_date_col >= resolved_start, serving_date_col <= resolved_end),
        )

        raw_daily = self._load_daily_counts(session, raw_model, raw_date_col, resolved_start, resolved_end)
        serving_daily = self._load_daily_counts(session, serving_model, serving_date_col, resolved_start, resolved_end)
        merged_dates = sorted(set(raw_daily.keys()) | set(serving_daily.keys()))
        daily_diffs: list[DatasetReconcileDailyDiff] = []
        for current_date in merged_dates:
            raw_count = raw_daily.get(current_date, 0)
            serving_count = serving_daily.get(current_date, 0)
            diff = raw_count - serving_count
            if diff != 0:
                daily_diffs.append(
                    DatasetReconcileDailyDiff(
                        trade_date=current_date,
                        raw_rows=raw_count,
                        serving_rows=serving_count,
                        diff=diff,
                    )
                )
            if len(daily_diffs) >= sample_limit:
                break

        return DatasetReconcileReport(
            dataset_key=dataset_key,
            start_date=resolved_start,
            end_date=resolved_end,
            raw_rows=raw_rows,
            serving_rows=serving_rows,
            daily_diffs=daily_diffs,
        )

    @staticmethod
    def _count_rows(session: Session, *, stmt: Select) -> int:
        return int(session.scalar(stmt) or 0)

    @staticmethod
    def _load_daily_counts(
        session: Session,
        model: type,
        date_col,
        start_date: date,
        end_date: date,
    ) -> dict[date, int]:
        rows = session.execute(
            select(date_col, func.count())
            .select_from(model)
            .where(date_col >= start_date, date_col <= end_date)
            .group_by(date_col)
        ).all()
        return {trade_date: int(count) for trade_date, count in rows if trade_date is not None}
