from __future__ import annotations

from sqlalchemy.orm import Session

from src.dao.etf_basic_dao import EtfBasicDAO
from src.dao.equity_adj_factor_dao import EquityAdjFactorDAO
from src.dao.equity_daily_bar_dao import EquityDailyBarDAO
from src.dao.equity_daily_basic_dao import EquityDailyBasicDAO
from src.dao.dividend_dao import EquityDividendDAO, RawDividendDAO
from src.dao.equity_moneyflow_dao import EquityMoneyflowDAO
from src.dao.generic import GenericDAO
from src.dao.holdernumber_dao import EquityHolderNumberDAO, RawHolderNumberDAO
from src.dao.index_basic_dao import IndexBasicDAO
from src.dao.index_daily_basic_dao import IndexDailyBasicDAO
from src.dao.index_monthly_bar_dao import IndexMonthlyBarDAO
from src.dao.index_weight_dao import IndexWeightDAO
from src.dao.index_weekly_bar_dao import IndexWeeklyBarDAO
from src.dao.security_dao import SecurityDAO
from src.dao.stk_period_bar_adj_dao import StkPeriodBarAdjDAO
from src.dao.stk_period_bar_dao import StkPeriodBarDAO
from src.dao.sync_job_state_dao import SyncJobStateDAO
from src.dao.sync_run_log_dao import SyncRunLogDAO
from src.dao.trade_calendar_dao import TradeCalendarDAO
from src.models.core.equity_block_trade import EquityBlockTrade
from src.models.core.equity_dividend import EquityDividend
from src.models.core.equity_holder_number import EquityHolderNumber
from src.models.core.equity_limit_list import EquityLimitList
from src.models.core.equity_top_list import EquityTopList
from src.models.core.etf_basic import EtfBasic
from src.models.core.fund_daily_bar import FundDailyBar
from src.models.core.index_basic import IndexBasic
from src.models.core.index_daily_basic import IndexDailyBasic
from src.models.core.index_daily_bar import IndexDailyBar
from src.models.core.index_monthly_bar import IndexMonthlyBar
from src.models.core.index_weight import IndexWeight
from src.models.core.index_weekly_bar import IndexWeeklyBar
from src.models.raw.raw_adj_factor import RawAdjFactor
from src.models.raw.raw_block_trade import RawBlockTrade
from src.models.raw.raw_daily import RawDaily
from src.models.raw.raw_daily_basic import RawDailyBasic
from src.models.raw.raw_dividend import RawDividend
from src.models.raw.raw_etf_basic import RawEtfBasic
from src.models.raw.raw_fund_daily import RawFundDaily
from src.models.raw.raw_holdernumber import RawHolderNumber
from src.models.raw.raw_index_basic import RawIndexBasic
from src.models.raw.raw_index_daily_basic import RawIndexDailyBasic
from src.models.raw.raw_index_daily import RawIndexDaily
from src.models.raw.raw_index_monthly_bar import RawIndexMonthlyBar
from src.models.raw.raw_index_weight import RawIndexWeight
from src.models.raw.raw_index_weekly_bar import RawIndexWeeklyBar
from src.models.raw.raw_limit_list import RawLimitList
from src.models.raw.raw_moneyflow import RawMoneyflow
from src.models.raw.raw_stock_basic import RawStockBasic
from src.models.raw.raw_stk_period_bar import RawStkPeriodBar
from src.models.raw.raw_stk_period_bar_adj import RawStkPeriodBarAdj
from src.models.raw.raw_top_list import RawTopList
from src.models.raw.raw_trade_cal import RawTradeCal
from src.models.core.stk_period_bar import StkPeriodBar
from src.models.core.stk_period_bar_adj import StkPeriodBarAdj


class DAOFactory:
    def __init__(self, session: Session) -> None:
        self.security = SecurityDAO(session)
        self.trade_calendar = TradeCalendarDAO(session)
        self.equity_daily_bar = EquityDailyBarDAO(session)
        self.equity_adj_factor = EquityAdjFactorDAO(session)
        self.equity_daily_basic = EquityDailyBasicDAO(session)
        self.equity_moneyflow = EquityMoneyflowDAO(session)
        self.equity_limit_list = GenericDAO(session, EquityLimitList)
        self.equity_top_list = GenericDAO(session, EquityTopList)
        self.equity_block_trade = GenericDAO(session, EquityBlockTrade)
        self.equity_dividend = EquityDividendDAO(session)
        self.etf_basic = EtfBasicDAO(session)
        self.fund_daily_bar = GenericDAO(session, FundDailyBar)
        self.stk_period_bar = StkPeriodBarDAO(session)
        self.stk_period_bar_adj = StkPeriodBarAdjDAO(session)
        self.index_basic = IndexBasicDAO(session)
        self.index_daily_bar = GenericDAO(session, IndexDailyBar)
        self.index_weekly_bar = IndexWeeklyBarDAO(session)
        self.index_monthly_bar = IndexMonthlyBarDAO(session)
        self.index_weight = IndexWeightDAO(session)
        self.index_daily_basic = IndexDailyBasicDAO(session)
        self.equity_holder_number = EquityHolderNumberDAO(session)
        self.sync_job_state = SyncJobStateDAO(session)
        self.sync_run_log = SyncRunLogDAO(session)

        self.raw_stock_basic = GenericDAO(session, RawStockBasic)
        self.raw_trade_cal = GenericDAO(session, RawTradeCal)
        self.raw_daily = GenericDAO(session, RawDaily)
        self.raw_adj_factor = GenericDAO(session, RawAdjFactor)
        self.raw_daily_basic = GenericDAO(session, RawDailyBasic)
        self.raw_moneyflow = GenericDAO(session, RawMoneyflow)
        self.raw_top_list = GenericDAO(session, RawTopList)
        self.raw_block_trade = GenericDAO(session, RawBlockTrade)
        self.raw_dividend = RawDividendDAO(session)
        self.raw_etf_basic = GenericDAO(session, RawEtfBasic)
        self.raw_fund_daily = GenericDAO(session, RawFundDaily)
        self.raw_stk_period_bar = GenericDAO(session, RawStkPeriodBar)
        self.raw_stk_period_bar_adj = GenericDAO(session, RawStkPeriodBarAdj)
        self.raw_index_basic = GenericDAO(session, RawIndexBasic)
        self.raw_index_daily = GenericDAO(session, RawIndexDaily)
        self.raw_index_weekly_bar = GenericDAO(session, RawIndexWeeklyBar)
        self.raw_index_monthly_bar = GenericDAO(session, RawIndexMonthlyBar)
        self.raw_index_weight = GenericDAO(session, RawIndexWeight)
        self.raw_index_daily_basic = GenericDAO(session, RawIndexDailyBasic)
        self.raw_holder_number = RawHolderNumberDAO(session)
        self.raw_limit_list = GenericDAO(session, RawLimitList)
