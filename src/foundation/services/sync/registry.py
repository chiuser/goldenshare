from __future__ import annotations

from sqlalchemy.orm import Session

from src.foundation.services.sync.sync_adj_factor_service import SyncAdjFactorService
from src.foundation.services.sync.sync_block_trade_service import SyncBlockTradeService
from src.foundation.services.sync.sync_biying_equity_daily_service import SyncBiyingEquityDailyService
from src.foundation.services.sync.sync_biying_moneyflow_service import SyncBiyingMoneyflowService
from src.foundation.services.sync.sync_dc_daily_service import SyncDcDailyService
from src.foundation.services.sync.sync_dc_index_service import SyncDcIndexService
from src.foundation.services.sync.sync_dc_member_service import SyncDcMemberService
from src.foundation.services.sync.sync_broker_recommend_service import SyncBrokerRecommendService
from src.foundation.services.sync.sync_daily_basic_service import SyncDailyBasicService
from src.foundation.services.sync.sync_dividend_service import SyncDividendService
from src.foundation.services.sync.sync_dc_hot_service import SyncDcHotService
from src.foundation.services.sync.sync_etf_basic_service import SyncEtfBasicService
from src.foundation.services.sync.sync_etf_index_service import SyncEtfIndexService
from src.foundation.services.sync.sync_equity_daily_service import SyncEquityDailyService
from src.foundation.services.sync.sync_equity_indicators_service import SyncEquityIndicatorsService
from src.foundation.services.sync.sync_fund_daily_service import SyncFundDailyService
from src.foundation.services.sync.sync_fund_adj_service import SyncFundAdjService
from src.foundation.services.sync.sync_holdernumber_service import SyncHolderNumberService
from src.foundation.services.sync.sync_hk_basic_service import SyncHkBasicService
from src.foundation.services.sync.sync_kpl_concept_cons_service import SyncKplConceptConsService
from src.foundation.services.sync.sync_kpl_list_service import SyncKplListService
from src.foundation.services.sync.sync_index_basic_service import SyncIndexBasicService
from src.foundation.services.sync.sync_index_daily_service import SyncIndexDailyService
from src.foundation.services.sync.sync_index_daily_basic_service import SyncIndexDailyBasicService
from src.foundation.services.sync.sync_index_monthly_service import SyncIndexMonthlyService
from src.foundation.services.sync.sync_index_weekly_service import SyncIndexWeeklyService
from src.foundation.services.sync.sync_index_weight_service import SyncIndexWeightService
from src.foundation.services.sync.sync_limit_list_service import SyncLimitListService
from src.foundation.services.sync.sync_limit_list_ths_service import SyncLimitListThsService
from src.foundation.services.sync.sync_limit_step_service import SyncLimitStepService
from src.foundation.services.sync.sync_stk_limit_service import SyncStkLimitService
from src.foundation.services.sync.sync_stk_nineturn_service import SyncStkNineTurnService
from src.foundation.services.sync.sync_limit_cpt_list_service import SyncLimitCptListService
from src.foundation.services.sync.sync_moneyflow_service import SyncMoneyflowService
from src.foundation.services.sync.sync_stock_basic_service import SyncStockBasicService
from src.foundation.services.sync.sync_stk_period_bar_adj_month_service import SyncStkPeriodBarAdjMonthService
from src.foundation.services.sync.sync_stk_period_bar_adj_week_service import SyncStkPeriodBarAdjWeekService
from src.foundation.services.sync.sync_stk_period_bar_month_service import SyncStkPeriodBarMonthService
from src.foundation.services.sync.sync_stk_period_bar_week_service import SyncStkPeriodBarWeekService
from src.foundation.services.sync.sync_top_list_service import SyncTopListService
from src.foundation.services.sync.sync_trade_calendar_service import SyncTradeCalendarService
from src.foundation.services.sync.sync_ths_daily_service import SyncThsDailyService
from src.foundation.services.sync.sync_ths_hot_service import SyncThsHotService
from src.foundation.services.sync.sync_ths_index_service import SyncThsIndexService
from src.foundation.services.sync.sync_ths_member_service import SyncThsMemberService
from src.foundation.services.sync.sync_us_basic_service import SyncUsBasicService


SYNC_SERVICE_REGISTRY = {
    "stock_basic": SyncStockBasicService,
    "biying_equity_daily": SyncBiyingEquityDailyService,
    "biying_moneyflow": SyncBiyingMoneyflowService,
    "hk_basic": SyncHkBasicService,
    "us_basic": SyncUsBasicService,
    "trade_cal": SyncTradeCalendarService,
    "daily": SyncEquityDailyService,
    "equity_indicators": SyncEquityIndicatorsService,
    "adj_factor": SyncAdjFactorService,
    "daily_basic": SyncDailyBasicService,
    "moneyflow": SyncMoneyflowService,
    "top_list": SyncTopListService,
    "block_trade": SyncBlockTradeService,
    "dividend": SyncDividendService,
    "etf_basic": SyncEtfBasicService,
    "etf_index": SyncEtfIndexService,
    "fund_daily": SyncFundDailyService,
    "fund_adj": SyncFundAdjService,
    "index_daily": SyncIndexDailyService,
    "index_basic": SyncIndexBasicService,
    "index_weekly": SyncIndexWeeklyService,
    "index_monthly": SyncIndexMonthlyService,
    "index_weight": SyncIndexWeightService,
    "index_daily_basic": SyncIndexDailyBasicService,
    "ths_index": SyncThsIndexService,
    "ths_member": SyncThsMemberService,
    "ths_daily": SyncThsDailyService,
    "ths_hot": SyncThsHotService,
    "dc_index": SyncDcIndexService,
    "dc_member": SyncDcMemberService,
    "dc_daily": SyncDcDailyService,
    "dc_hot": SyncDcHotService,
    "kpl_list": SyncKplListService,
    "kpl_concept_cons": SyncKplConceptConsService,
    "limit_list_ths": SyncLimitListThsService,
    "limit_step": SyncLimitStepService,
    "limit_cpt_list": SyncLimitCptListService,
    "stk_holdernumber": SyncHolderNumberService,
    "limit_list_d": SyncLimitListService,
    "stk_limit": SyncStkLimitService,
    "stk_nineturn": SyncStkNineTurnService,
    "stk_period_bar_week": SyncStkPeriodBarWeekService,
    "stk_period_bar_month": SyncStkPeriodBarMonthService,
    "stk_period_bar_adj_week": SyncStkPeriodBarAdjWeekService,
    "stk_period_bar_adj_month": SyncStkPeriodBarAdjMonthService,
    "broker_recommend": SyncBrokerRecommendService,
}


def build_sync_service(resource: str, session: Session):
    service_cls = SYNC_SERVICE_REGISTRY[resource]
    return service_cls(session)
