from __future__ import annotations

from src.foundation.models.core.equity_block_trade import EquityBlockTrade
from src.foundation.models.core.board_moneyflow_dc import BoardMoneyflowDc
from src.foundation.models.core.concept_moneyflow_ths import ConceptMoneyflowThs
from src.foundation.models.core.equity_cyq_perf import EquityCyqPerf
from src.foundation.models.core.equity_dividend import EquityDividend
from src.foundation.models.core.equity_factor_pro import EquityFactorPro
from src.foundation.models.core.equity_holder_number import EquityHolderNumber
from src.foundation.models.core.equity_limit_list import EquityLimitList
from src.foundation.models.core.equity_margin import EquityMargin
from src.foundation.models.core.equity_moneyflow import EquityMoneyflow
from src.foundation.models.core.equity_moneyflow_dc import EquityMoneyflowDc
from src.foundation.models.core.equity_moneyflow_ths import EquityMoneyflowThs
from src.foundation.models.core.equity_nineturn import EquityNineTurn
from src.foundation.models.core.equity_stk_limit import EquityStkLimit
from src.foundation.models.core.equity_stock_st import EquityStockSt
from src.foundation.models.core.equity_suspend_d import EquitySuspendD
from src.foundation.models.core.equity_top_list import EquityTopList
from src.foundation.models.core.etf_basic import EtfBasic
from src.foundation.models.core.etf_index import EtfIndex
from src.foundation.models.core.fund_adj_factor import FundAdjFactor
from src.foundation.models.core.fund_daily_bar import FundDailyBar
from src.foundation.models.core.hk_security import HkSecurity
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.dc_hot import DcHot
from src.foundation.models.core.dc_index import DcIndex
from src.foundation.models.core.dc_member import DcMember
from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core.index_daily_bar import IndexDailyBar
from src.foundation.models.core.index_daily_basic import IndexDailyBasic
from src.foundation.models.core.index_monthly_bar import IndexMonthlyBar
from src.foundation.models.core.index_weight import IndexWeight
from src.foundation.models.core.industry_moneyflow_ths import IndustryMoneyflowThs
from src.foundation.models.core.index_weekly_bar import IndexWeeklyBar
from src.foundation.models.core.kpl_concept_cons import KplConceptCons
from src.foundation.models.core.kpl_list import KplList
from src.foundation.models.core.limit_cpt_list import LimitCptList
from src.foundation.models.core.limit_list_ths import LimitListThs
from src.foundation.models.core.limit_step import LimitStep
from src.foundation.models.core.market_moneyflow_dc import MarketMoneyflowDc
from src.foundation.models.core.trade_calendar import TradeCalendar
from src.foundation.models.core.us_security import UsSecurity
from src.foundation.models.core.ths_daily import ThsDaily
from src.foundation.models.core.ths_hot import ThsHot
from src.foundation.models.core.ths_index import ThsIndex
from src.foundation.models.core.ths_member import ThsMember
from src.foundation.models.core_serving.equity_adj_factor import EquityAdjFactor
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar
from src.foundation.models.core_serving.equity_daily_basic import EquityDailyBasic
from src.foundation.models.core_serving.index_daily_serving import IndexDailyServing
from src.foundation.models.core_serving.index_monthly_serving import IndexMonthlyServing
from src.foundation.models.core_serving.index_weekly_serving import IndexWeeklyServing
from src.foundation.models.core_serving.security_serving import Security
from src.foundation.models.core_serving.stk_period_bar import StkPeriodBar
from src.foundation.models.core_serving.stk_period_bar_adj import StkPeriodBarAdj
from src.foundation.models.raw_multi.raw_biying_equity_daily_bar import RawBiyingEquityDailyBar
from src.foundation.models.raw_multi.raw_biying_moneyflow import RawBiyingMoneyflow


# Dataset-specific observed-range filters for shared tables.
OBSERVED_DATE_FILTERS: dict[str, tuple[str, str]] = {
    "stk_period_bar_week": ("freq", "week"),
    "stk_period_bar_month": ("freq", "month"),
    "stk_period_bar_adj_week": ("freq", "week"),
    "stk_period_bar_adj_month": ("freq", "month"),
}

OBSERVED_DATE_AUTHORITATIVE_KEYS = {
    "stk_period_bar_week",
    "stk_period_bar_month",
    "stk_period_bar_adj_week",
    "stk_period_bar_adj_month",
}

OBSERVED_DATE_MODEL_REGISTRY: dict[str, type] = {
    "core_serving.security_serving": Security,
    "core_serving.hk_security": HkSecurity,
    "core_serving.us_security": UsSecurity,
    "core_serving.trade_calendar": TradeCalendar,
    "core_serving.etf_basic": EtfBasic,
    "core_serving.etf_index": EtfIndex,
    "core_serving.index_basic": IndexBasic,
    "core_serving.equity_daily_bar": EquityDailyBar,
    "core.equity_adj_factor": EquityAdjFactor,
    "core_serving.equity_daily_basic": EquityDailyBasic,
    "core_serving.equity_cyq_perf": EquityCyqPerf,
    "core_serving.equity_factor_pro": EquityFactorPro,
    "core_serving.equity_moneyflow": EquityMoneyflow,
    "core_serving.equity_moneyflow_ths": EquityMoneyflowThs,
    "core_serving.equity_moneyflow_dc": EquityMoneyflowDc,
    "core_serving.industry_moneyflow_ths": IndustryMoneyflowThs,
    "core_serving.board_moneyflow_dc": BoardMoneyflowDc,
    "core_serving.market_moneyflow_dc": MarketMoneyflowDc,
    "core_serving.concept_moneyflow_ths": ConceptMoneyflowThs,
    "core_serving.equity_margin": EquityMargin,
    "core_serving.equity_top_list": EquityTopList,
    "core_serving.equity_block_trade": EquityBlockTrade,
    "core_serving.equity_limit_list": EquityLimitList,
    "core_serving.equity_stk_limit": EquityStkLimit,
    "core_serving.equity_stock_st": EquityStockSt,
    "core_serving.equity_nineturn": EquityNineTurn,
    "core_serving.equity_suspend_d": EquitySuspendD,
    "core_serving.equity_dividend": EquityDividend,
    "core_serving.equity_holder_number": EquityHolderNumber,
    "core_serving.stk_period_bar": StkPeriodBar,
    "core_serving.stk_period_bar_adj": StkPeriodBarAdj,
    "core_serving.fund_daily_bar": FundDailyBar,
    "core.fund_adj_factor": FundAdjFactor,
    "core.index_daily_bar": IndexDailyBar,
    "core_serving.index_daily_serving": IndexDailyServing,
    "core.index_weekly_bar": IndexWeeklyBar,
    "core_serving.index_weekly_serving": IndexWeeklyServing,
    "core.index_monthly_bar": IndexMonthlyBar,
    "core_serving.index_monthly_serving": IndexMonthlyServing,
    "core_serving.index_daily_basic": IndexDailyBasic,
    "core_serving.index_weight": IndexWeight,
    "core.equity_cyq_perf": EquityCyqPerf,
    "core.equity_factor_pro": EquityFactorPro,
    "core.equity_margin": EquityMargin,
    "core.equity_moneyflow_ths": EquityMoneyflowThs,
    "core.equity_moneyflow_dc": EquityMoneyflowDc,
    "core.industry_moneyflow_ths": IndustryMoneyflowThs,
    "core.board_moneyflow_dc": BoardMoneyflowDc,
    "core.market_moneyflow_dc": MarketMoneyflowDc,
    "core.concept_moneyflow_ths": ConceptMoneyflowThs,
    "core.equity_stk_limit": EquityStkLimit,
    "core.equity_stock_st": EquityStockSt,
    "core.equity_nineturn": EquityNineTurn,
    "core.equity_suspend_d": EquitySuspendD,
    "core_serving.ths_index": ThsIndex,
    "core_serving.ths_member": ThsMember,
    "core_serving.ths_daily": ThsDaily,
    "core_serving.ths_hot": ThsHot,
    "core_serving.dc_index": DcIndex,
    "core_serving.dc_member": DcMember,
    "core_serving.dc_daily": DcDaily,
    "core_serving.dc_hot": DcHot,
    "core_serving.kpl_list": KplList,
    "core_serving.kpl_concept_cons": KplConceptCons,
    "core_serving.limit_list_ths": LimitListThs,
    "core_serving.limit_step": LimitStep,
    "core_serving.limit_cpt_list": LimitCptList,
    "raw_biying.equity_daily_bar": RawBiyingEquityDailyBar,
    "raw_biying.moneyflow": RawBiyingMoneyflow,
    # Compatible aliases for historical sync_job_state.target_table values.
    "core.trade_calendar": TradeCalendar,
    "core.equity_daily_bar": EquityDailyBar,
    "core.equity_daily_basic": EquityDailyBasic,
    "core.equity_top_list": EquityTopList,
    "core.equity_block_trade": EquityBlockTrade,
    "core.equity_limit_list": EquityLimitList,
    "core.stk_period_bar": StkPeriodBar,
    "core.stk_period_bar_adj": StkPeriodBarAdj,
    "core.fund_daily_bar": FundDailyBar,
    "core.index_daily_serving": IndexDailyServing,
    "core.index_weekly_serving": IndexWeeklyServing,
    "core.index_monthly_serving": IndexMonthlyServing,
    "core.index_daily_basic": IndexDailyBasic,
    "core.index_weight": IndexWeight,
}
