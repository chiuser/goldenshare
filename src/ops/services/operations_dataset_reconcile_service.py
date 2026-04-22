from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import Select, except_, func, select
from sqlalchemy.orm import Session

from src.foundation.models.core.dc_index import DcIndex
from src.foundation.models.core.equity_limit_list import EquityLimitList
from src.foundation.models.core.board_moneyflow_dc import BoardMoneyflowDc
from src.foundation.models.core.concept_moneyflow_ths import ConceptMoneyflowThs
from src.foundation.models.core.dc_member import DcMember
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.dc_hot import DcHot
from src.foundation.models.core.equity_block_trade import EquityBlockTrade
from src.foundation.models.core.equity_cyq_perf import EquityCyqPerf
from src.foundation.models.core.equity_dividend import EquityDividend
from src.foundation.models.core.equity_holder_number import EquityHolderNumber
from src.foundation.models.core.fund_daily_bar import FundDailyBar
from src.foundation.models.core.index_daily_basic import IndexDailyBasic
from src.foundation.models.core.index_weight import IndexWeight
from src.foundation.models.core.limit_list_ths import LimitListThs
from src.foundation.models.core.equity_moneyflow import EquityMoneyflow
from src.foundation.models.core.equity_nineturn import EquityNineTurn
from src.foundation.models.core.equity_stock_st import EquityStockSt
from src.foundation.models.core.equity_top_list import EquityTopList
from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.equity_daily_basic import EquityDailyBasic
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
from src.foundation.models.core.industry_moneyflow_ths import IndustryMoneyflowThs
from src.foundation.models.core.equity_margin import EquityMargin
from src.foundation.models.core.limit_cpt_list import LimitCptList
from src.foundation.models.core.limit_step import LimitStep
from src.foundation.models.core.market_moneyflow_dc import MarketMoneyflowDc
from src.foundation.models.core.equity_suspend_d import EquitySuspendD
from src.foundation.models.core.equity_stk_limit import EquityStkLimit
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.raw.raw_daily_basic import RawDailyBasic
from src.foundation.models.raw.raw_daily import RawDaily
from src.foundation.models.raw.raw_cyq_perf import RawCyqPerf
from src.foundation.models.raw.raw_adj_factor import RawAdjFactor
from src.foundation.models.raw.raw_dc_index import RawDcIndex
from src.foundation.models.raw.raw_fund_daily import RawFundDaily
from src.foundation.models.raw.raw_index_daily import RawIndexDaily
from src.foundation.models.raw.raw_index_daily_basic import RawIndexDailyBasic
from src.foundation.models.raw.raw_limit_list import RawLimitList
from src.foundation.models.raw.raw_limit_list_ths import RawLimitListThs
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
from src.foundation.models.raw.raw_dc_daily import RawDcDaily
from src.foundation.models.raw.raw_dc_hot import RawDcHot
from src.foundation.models.raw.raw_dividend import RawDividend
from src.foundation.models.raw.raw_stock_st import RawStockSt
from src.foundation.models.raw.raw_stk_nineturn import RawStkNineTurn
from src.foundation.models.raw.raw_stk_period_bar import RawStkPeriodBar
from src.foundation.models.raw.raw_stk_period_bar_adj import RawStkPeriodBarAdj
from src.foundation.models.raw.raw_suspend_d import RawSuspendD
from src.foundation.models.raw.raw_stk_limit import RawStkLimit
from src.foundation.models.raw.raw_top_list import RawTopList
from src.foundation.models.raw.raw_trade_cal import RawTradeCal
from src.foundation.models.raw.raw_holdernumber import RawHolderNumber
from src.foundation.models.raw.raw_index_weight import RawIndexWeight
from src.foundation.models.raw.raw_ths_daily import RawThsDaily
from src.foundation.models.raw.raw_ths_hot import RawThsHot
from src.foundation.models.raw.raw_ths_member import RawThsMember
from src.foundation.models.core.equity_moneyflow_dc import EquityMoneyflowDc
from src.foundation.models.core.equity_moneyflow_ths import EquityMoneyflowThs
from src.foundation.models.core.fund_adj_factor import FundAdjFactor
from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core.etf_basic import EtfBasic
from src.foundation.models.core.etf_index import EtfIndex
from src.foundation.models.core.hk_security import HkSecurity
from src.foundation.models.core.us_security import UsSecurity
from src.foundation.models.core.ths_index import ThsIndex
from src.foundation.models.core.kpl_list import KplList
from src.foundation.models.core.kpl_concept_cons import KplConceptCons
from src.foundation.models.core.broker_recommend import BrokerRecommend
from src.foundation.models.core.ths_daily import ThsDaily
from src.foundation.models.core.ths_hot import ThsHot
from src.foundation.models.raw.raw_fund_adj import RawFundAdj
from src.foundation.models.raw.raw_index_basic import RawIndexBasic
from src.foundation.models.raw.raw_etf_basic import RawEtfBasic
from src.foundation.models.raw.raw_etf_index import RawEtfIndex
from src.foundation.models.raw.raw_hk_basic import RawHkBasic
from src.foundation.models.raw.raw_us_basic import RawUsBasic
from src.foundation.models.raw.raw_ths_index import RawThsIndex
from src.foundation.models.raw.raw_kpl_list import RawKplList
from src.foundation.models.raw.raw_kpl_concept_cons import RawKplConceptCons
from src.foundation.models.raw.raw_broker_recommend import RawBrokerRecommend
from src.foundation.models.core_serving.stk_period_bar import StkPeriodBar
from src.foundation.models.core_serving.stk_period_bar_adj import StkPeriodBarAdj
from src.foundation.models.core_serving.ths_member import ThsMember


@dataclass(slots=True, frozen=True)
class DatasetReconcileConfig:
    raw_model: type
    serving_model: type
    mode: str
    raw_date_field: str | None = None
    serving_date_field: str | None = None
    key_fields: tuple[str, ...] | None = None
    raw_filters: dict[str, str] | None = None
    serving_filters: dict[str, str] | None = None


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
    reconcile_mode: str = "daily"
    raw_distinct_keys: int | None = None
    serving_distinct_keys: int | None = None
    snapshot_key_diffs: list[str] = field(default_factory=list)
    daily_diffs: list[DatasetReconcileDailyDiff] = field(default_factory=list)

    @property
    def abs_diff(self) -> int:
        return abs(self.raw_rows - self.serving_rows)

    @property
    def distinct_abs_diff(self) -> int | None:
        if self.raw_distinct_keys is None or self.serving_distinct_keys is None:
            return None
        return abs(self.raw_distinct_keys - self.serving_distinct_keys)


class DatasetReconcileService:
    SUPPORTED_DATASETS: dict[str, DatasetReconcileConfig] = {
        "adj_factor": DatasetReconcileConfig(
            raw_model=RawAdjFactor,
            serving_model=EquityAdjFactor,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "daily": DatasetReconcileConfig(
            raw_model=RawDaily,
            serving_model=EquityDailyBar,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "trade_cal": DatasetReconcileConfig(
            raw_model=RawTradeCal,
            serving_model=TradeCalendar,
            mode="daily",
            raw_date_field="cal_date",
            serving_date_field="trade_date",
        ),
        "daily_basic": DatasetReconcileConfig(
            raw_model=RawDailyBasic,
            serving_model=EquityDailyBasic,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "cyq_perf": DatasetReconcileConfig(
            raw_model=RawCyqPerf,
            serving_model=EquityCyqPerf,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "dc_index": DatasetReconcileConfig(
            raw_model=RawDcIndex,
            serving_model=DcIndex,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "fund_daily": DatasetReconcileConfig(
            raw_model=RawFundDaily,
            serving_model=FundDailyBar,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "index_daily": DatasetReconcileConfig(
            raw_model=RawIndexDaily,
            serving_model=IndexDailyServing,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "index_daily_basic": DatasetReconcileConfig(
            raw_model=RawIndexDailyBasic,
            serving_model=IndexDailyBasic,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "limit_list_d": DatasetReconcileConfig(
            raw_model=RawLimitList,
            serving_model=EquityLimitList,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "limit_list_ths": DatasetReconcileConfig(
            raw_model=RawLimitListThs,
            serving_model=LimitListThs,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "stk_limit": DatasetReconcileConfig(
            raw_model=RawStkLimit,
            serving_model=EquityStkLimit,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "suspend_d": DatasetReconcileConfig(
            raw_model=RawSuspendD,
            serving_model=EquitySuspendD,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "margin": DatasetReconcileConfig(
            raw_model=RawMargin,
            serving_model=EquityMargin,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "limit_step": DatasetReconcileConfig(
            raw_model=RawLimitStep,
            serving_model=LimitStep,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "limit_cpt_list": DatasetReconcileConfig(
            raw_model=RawLimitCptList,
            serving_model=LimitCptList,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "moneyflow": DatasetReconcileConfig(
            raw_model=RawMoneyflow,
            serving_model=EquityMoneyflow,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "moneyflow_ths": DatasetReconcileConfig(
            raw_model=RawMoneyflowThs,
            serving_model=EquityMoneyflowThs,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "moneyflow_dc": DatasetReconcileConfig(
            raw_model=RawMoneyflowDc,
            serving_model=EquityMoneyflowDc,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "moneyflow_cnt_ths": DatasetReconcileConfig(
            raw_model=RawMoneyflowCntThs,
            serving_model=ConceptMoneyflowThs,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "moneyflow_ind_ths": DatasetReconcileConfig(
            raw_model=RawMoneyflowIndThs,
            serving_model=IndustryMoneyflowThs,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "moneyflow_ind_dc": DatasetReconcileConfig(
            raw_model=RawMoneyflowIndDc,
            serving_model=BoardMoneyflowDc,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "moneyflow_mkt_dc": DatasetReconcileConfig(
            raw_model=RawMoneyflowMktDc,
            serving_model=MarketMoneyflowDc,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "top_list": DatasetReconcileConfig(
            raw_model=RawTopList,
            serving_model=EquityTopList,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "block_trade": DatasetReconcileConfig(
            raw_model=RawBlockTrade,
            serving_model=EquityBlockTrade,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "stock_st": DatasetReconcileConfig(
            raw_model=RawStockSt,
            serving_model=EquityStockSt,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "stk_nineturn": DatasetReconcileConfig(
            raw_model=RawStkNineTurn,
            serving_model=EquityNineTurn,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "dc_member": DatasetReconcileConfig(
            raw_model=RawDcMember,
            serving_model=DcMember,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "ths_member": DatasetReconcileConfig(
            raw_model=RawThsMember,
            serving_model=ThsMember,
            mode="snapshot",
        ),
        "ths_daily": DatasetReconcileConfig(
            raw_model=RawThsDaily,
            serving_model=ThsDaily,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "dc_daily": DatasetReconcileConfig(
            raw_model=RawDcDaily,
            serving_model=DcDaily,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "ths_hot": DatasetReconcileConfig(
            raw_model=RawThsHot,
            serving_model=ThsHot,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "dc_hot": DatasetReconcileConfig(
            raw_model=RawDcHot,
            serving_model=DcHot,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "stk_period_bar_week": DatasetReconcileConfig(
            raw_model=RawStkPeriodBar,
            serving_model=StkPeriodBar,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
            raw_filters={"freq": "week"},
            serving_filters={"freq": "week"},
        ),
        "stk_period_bar_month": DatasetReconcileConfig(
            raw_model=RawStkPeriodBar,
            serving_model=StkPeriodBar,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
            raw_filters={"freq": "month"},
            serving_filters={"freq": "month"},
        ),
        "stk_period_bar_adj_week": DatasetReconcileConfig(
            raw_model=RawStkPeriodBarAdj,
            serving_model=StkPeriodBarAdj,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
            raw_filters={"freq": "week"},
            serving_filters={"freq": "week"},
        ),
        "stk_period_bar_adj_month": DatasetReconcileConfig(
            raw_model=RawStkPeriodBarAdj,
            serving_model=StkPeriodBarAdj,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
            raw_filters={"freq": "month"},
            serving_filters={"freq": "month"},
        ),
        "fund_adj": DatasetReconcileConfig(
            raw_model=RawFundAdj,
            serving_model=FundAdjFactor,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "dividend": DatasetReconcileConfig(
            raw_model=RawDividend,
            serving_model=EquityDividend,
            mode="daily",
            raw_date_field="ann_date",
            serving_date_field="ann_date",
        ),
        "stk_holdernumber": DatasetReconcileConfig(
            raw_model=RawHolderNumber,
            serving_model=EquityHolderNumber,
            mode="daily",
            raw_date_field="ann_date",
            serving_date_field="ann_date",
        ),
        "index_weight": DatasetReconcileConfig(
            raw_model=RawIndexWeight,
            serving_model=IndexWeight,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "index_basic": DatasetReconcileConfig(
            raw_model=RawIndexBasic,
            serving_model=IndexBasic,
            mode="snapshot",
        ),
        "etf_basic": DatasetReconcileConfig(
            raw_model=RawEtfBasic,
            serving_model=EtfBasic,
            mode="snapshot",
        ),
        "etf_index": DatasetReconcileConfig(
            raw_model=RawEtfIndex,
            serving_model=EtfIndex,
            mode="snapshot",
        ),
        "hk_basic": DatasetReconcileConfig(
            raw_model=RawHkBasic,
            serving_model=HkSecurity,
            mode="snapshot",
        ),
        "us_basic": DatasetReconcileConfig(
            raw_model=RawUsBasic,
            serving_model=UsSecurity,
            mode="snapshot",
        ),
        "ths_index": DatasetReconcileConfig(
            raw_model=RawThsIndex,
            serving_model=ThsIndex,
            mode="snapshot",
        ),
        "kpl_list": DatasetReconcileConfig(
            raw_model=RawKplList,
            serving_model=KplList,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "kpl_concept_cons": DatasetReconcileConfig(
            raw_model=RawKplConceptCons,
            serving_model=KplConceptCons,
            mode="daily",
            raw_date_field="trade_date",
            serving_date_field="trade_date",
        ),
        "broker_recommend": DatasetReconcileConfig(
            raw_model=RawBrokerRecommend,
            serving_model=BrokerRecommend,
            mode="snapshot",
        ),
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

        resolved_end = end_date or date.today()
        resolved_start = start_date or (resolved_end - timedelta(days=7))
        if resolved_start > resolved_end:
            raise ValueError("start_date must be <= end_date")

        if config.mode == "snapshot":
            raw_count_stmt = select(func.count()).select_from(config.raw_model)
            serving_count_stmt = select(func.count()).select_from(config.serving_model)
            raw_rows = self._count_rows(
                session,
                stmt=self._apply_filters(raw_count_stmt, config.raw_model, config.raw_filters),
            )
            serving_rows = self._count_rows(
                session,
                stmt=self._apply_filters(serving_count_stmt, config.serving_model, config.serving_filters),
            )
            raw_distinct = self._count_distinct_keys(
                session,
                model=config.raw_model,
                key_fields=config.key_fields,
                static_filters=config.raw_filters,
            )
            serving_distinct = self._count_distinct_keys(
                session,
                model=config.serving_model,
                key_fields=config.key_fields,
                static_filters=config.serving_filters,
            )
            key_diffs = self._load_key_diff_samples(
                session,
                raw_model=config.raw_model,
                serving_model=config.serving_model,
                key_fields=config.key_fields,
                raw_filters=config.raw_filters,
                serving_filters=config.serving_filters,
                sample_limit=sample_limit,
            )
            return DatasetReconcileReport(
                dataset_key=dataset_key,
                start_date=resolved_start,
                end_date=resolved_end,
                raw_rows=raw_rows,
                serving_rows=serving_rows,
                reconcile_mode="snapshot",
                raw_distinct_keys=raw_distinct,
                serving_distinct_keys=serving_distinct,
                snapshot_key_diffs=key_diffs,
            )

        if not config.raw_date_field or not config.serving_date_field:
            raise ValueError(f"dataset={dataset_key} missing date fields for daily reconcile mode")

        raw_date_col = getattr(config.raw_model, config.raw_date_field)
        serving_date_col = getattr(config.serving_model, config.serving_date_field)

        raw_rows = self._count_rows(
            session,
            stmt=self._apply_filters(
                select(func.count()).select_from(config.raw_model).where(raw_date_col >= resolved_start, raw_date_col <= resolved_end),
                config.raw_model,
                config.raw_filters,
            ),
        )
        serving_rows = self._count_rows(
            session,
            stmt=self._apply_filters(
                select(func.count()).select_from(config.serving_model).where(
                    serving_date_col >= resolved_start, serving_date_col <= resolved_end
                ),
                config.serving_model,
                config.serving_filters,
            ),
        )

        raw_daily = self._load_daily_counts(
            session,
            config.raw_model,
            raw_date_col,
            resolved_start,
            resolved_end,
            static_filters=config.raw_filters,
        )
        serving_daily = self._load_daily_counts(
            session,
            config.serving_model,
            serving_date_col,
            resolved_start,
            resolved_end,
            static_filters=config.serving_filters,
        )
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
            reconcile_mode="daily",
            daily_diffs=daily_diffs,
        )

    @staticmethod
    def _count_rows(session: Session, *, stmt: Select) -> int:
        return int(session.scalar(stmt) or 0)

    @staticmethod
    def _resolve_key_columns(model: type, key_fields: tuple[str, ...] | None = None) -> list:
        if key_fields:
            return [getattr(model, key) for key in key_fields]
        return [getattr(model, col.name) for col in model.__table__.primary_key.columns]

    def _count_distinct_keys(
        self,
        session: Session,
        *,
        model: type,
        key_fields: tuple[str, ...] | None = None,
        static_filters: dict[str, str] | None = None,
    ) -> int:
        key_columns = self._resolve_key_columns(model, key_fields)
        if not key_columns:
            return 0
        key_stmt = select(*key_columns).distinct()
        key_stmt = self._apply_filters(key_stmt, model, static_filters)
        stmt = key_stmt.subquery()
        return self._count_rows(session, stmt=select(func.count()).select_from(stmt))

    def _load_key_diff_samples(
        self,
        session: Session,
        *,
        raw_model: type,
        serving_model: type,
        key_fields: tuple[str, ...] | None = None,
        raw_filters: dict[str, str] | None = None,
        serving_filters: dict[str, str] | None = None,
        sample_limit: int,
    ) -> list[str]:
        if sample_limit <= 0:
            return []
        raw_keys = self._resolve_key_columns(raw_model, key_fields)
        serving_keys = self._resolve_key_columns(serving_model, key_fields)
        if not raw_keys or not serving_keys:
            return []

        raw_stmt = select(*raw_keys).distinct()
        raw_stmt = self._apply_filters(raw_stmt, raw_model, raw_filters)
        serving_stmt = select(*serving_keys).distinct()
        serving_stmt = self._apply_filters(serving_stmt, serving_model, serving_filters)
        raw_only_stmt = except_(
            raw_stmt,
            serving_stmt,
        ).limit(sample_limit)
        raw_only_rows = session.execute(raw_only_stmt).all()
        samples = [f"raw_only:{self._format_key_row(row)}" for row in raw_only_rows]
        if len(samples) >= sample_limit:
            return samples

        remaining = sample_limit - len(samples)
        serving_only_stmt = except_(
            serving_stmt,
            raw_stmt,
        ).limit(remaining)
        serving_only_rows = session.execute(serving_only_stmt).all()
        samples.extend(f"serving_only:{self._format_key_row(row)}" for row in serving_only_rows)
        return samples

    @staticmethod
    def _format_key_row(row) -> str:  # type: ignore[no-untyped-def]
        values = [str(value) if value is not None else "NULL" for value in tuple(row)]
        return "|".join(values)

    @staticmethod
    def _load_daily_counts(
        session: Session,
        model: type,
        date_col,
        start_date: date,
        end_date: date,
        static_filters: dict[str, str] | None = None,
    ) -> dict[date, int]:
        stmt = (
            select(date_col, func.count())
            .select_from(model)
            .where(date_col >= start_date, date_col <= end_date)
            .group_by(date_col)
        )
        stmt = DatasetReconcileService._apply_filters(stmt, model, static_filters)
        rows = session.execute(stmt).all()
        return {trade_date: int(count) for trade_date, count in rows if trade_date is not None}

    @staticmethod
    def _apply_filters(stmt, model: type, filters: dict[str, str] | None):  # type: ignore[no-untyped-def]
        if not filters:
            return stmt
        for field_name, expected in filters.items():
            stmt = stmt.where(getattr(model, field_name) == expected)
        return stmt
