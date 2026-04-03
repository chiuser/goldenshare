from __future__ import annotations

from sqlalchemy.orm import Session

from src.services.sync.sync_adj_factor_service import SyncAdjFactorService
from src.services.sync.sync_block_trade_service import SyncBlockTradeService
from src.services.sync.sync_dc_daily_service import SyncDcDailyService
from src.services.sync.sync_dc_index_service import SyncDcIndexService
from src.services.sync.sync_dc_member_service import SyncDcMemberService
from src.services.sync.sync_daily_basic_service import SyncDailyBasicService
from src.services.sync.sync_dividend_service import SyncDividendService
from src.services.sync.sync_dc_hot_service import SyncDcHotService
from src.services.sync.sync_etf_basic_service import SyncEtfBasicService
from src.services.sync.sync_equity_daily_service import SyncEquityDailyService
from src.services.sync.sync_fund_daily_service import SyncFundDailyService
from src.services.sync.sync_holdernumber_service import SyncHolderNumberService
from src.services.sync.sync_hk_basic_service import SyncHkBasicService
from src.services.sync.sync_kpl_concept_cons_service import SyncKplConceptConsService
from src.services.sync.sync_kpl_list_service import SyncKplListService
from src.services.sync.sync_index_basic_service import SyncIndexBasicService
from src.services.sync.sync_index_daily_service import SyncIndexDailyService
from src.services.sync.sync_index_daily_basic_service import SyncIndexDailyBasicService
from src.services.sync.sync_index_monthly_service import SyncIndexMonthlyService
from src.services.sync.sync_index_weekly_service import SyncIndexWeeklyService
from src.services.sync.sync_index_weight_service import SyncIndexWeightService
from src.services.sync.sync_limit_list_service import SyncLimitListService
from src.services.sync.sync_moneyflow_service import SyncMoneyflowService
from src.services.sync.sync_stock_basic_service import SyncStockBasicService
from src.services.sync.sync_stk_period_bar_adj_month_service import SyncStkPeriodBarAdjMonthService
from src.services.sync.sync_stk_period_bar_adj_week_service import SyncStkPeriodBarAdjWeekService
from src.services.sync.sync_stk_period_bar_month_service import SyncStkPeriodBarMonthService
from src.services.sync.sync_stk_period_bar_week_service import SyncStkPeriodBarWeekService
from src.services.sync.sync_top_list_service import SyncTopListService
from src.services.sync.sync_trade_calendar_service import SyncTradeCalendarService
from src.services.sync.sync_ths_daily_service import SyncThsDailyService
from src.services.sync.sync_ths_hot_service import SyncThsHotService
from src.services.sync.sync_ths_index_service import SyncThsIndexService
from src.services.sync.sync_ths_member_service import SyncThsMemberService
from src.services.sync.sync_us_basic_service import SyncUsBasicService


SYNC_SERVICE_REGISTRY = {
    "stock_basic": SyncStockBasicService,
    "hk_basic": SyncHkBasicService,
    "us_basic": SyncUsBasicService,
    "trade_cal": SyncTradeCalendarService,
    "daily": SyncEquityDailyService,
    "adj_factor": SyncAdjFactorService,
    "daily_basic": SyncDailyBasicService,
    "moneyflow": SyncMoneyflowService,
    "top_list": SyncTopListService,
    "block_trade": SyncBlockTradeService,
    "dividend": SyncDividendService,
    "etf_basic": SyncEtfBasicService,
    "fund_daily": SyncFundDailyService,
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
    "stk_holdernumber": SyncHolderNumberService,
    "limit_list_d": SyncLimitListService,
    "stk_period_bar_week": SyncStkPeriodBarWeekService,
    "stk_period_bar_month": SyncStkPeriodBarMonthService,
    "stk_period_bar_adj_week": SyncStkPeriodBarAdjWeekService,
    "stk_period_bar_adj_month": SyncStkPeriodBarAdjMonthService,
}


def build_sync_service(resource: str, session: Session):
    service_cls = SYNC_SERVICE_REGISTRY[resource]
    return service_cls(session)
