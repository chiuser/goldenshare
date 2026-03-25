from __future__ import annotations

from sqlalchemy.orm import Session

from src.dao.equity_adj_factor_dao import EquityAdjFactorDAO
from src.dao.equity_daily_bar_dao import EquityDailyBarDAO
from src.dao.equity_daily_basic_dao import EquityDailyBasicDAO
from src.dao.equity_moneyflow_dao import EquityMoneyflowDAO
from src.dao.generic import GenericDAO
from src.dao.security_dao import SecurityDAO
from src.dao.sync_job_state_dao import SyncJobStateDAO
from src.dao.sync_run_log_dao import SyncRunLogDAO
from src.dao.trade_calendar_dao import TradeCalendarDAO
from src.models.core.equity_block_trade import EquityBlockTrade
from src.models.core.equity_dividend import EquityDividend
from src.models.core.equity_holder_number import EquityHolderNumber
from src.models.core.equity_limit_list import EquityLimitList
from src.models.core.equity_top_list import EquityTopList
from src.models.core.fund_daily_bar import FundDailyBar
from src.models.core.index_daily_bar import IndexDailyBar
from src.models.raw.raw_adj_factor import RawAdjFactor
from src.models.raw.raw_block_trade import RawBlockTrade
from src.models.raw.raw_daily import RawDaily
from src.models.raw.raw_daily_basic import RawDailyBasic
from src.models.raw.raw_dividend import RawDividend
from src.models.raw.raw_fund_daily import RawFundDaily
from src.models.raw.raw_holdernumber import RawHolderNumber
from src.models.raw.raw_index_daily import RawIndexDaily
from src.models.raw.raw_limit_list import RawLimitList
from src.models.raw.raw_moneyflow import RawMoneyflow
from src.models.raw.raw_stock_basic import RawStockBasic
from src.models.raw.raw_top_list import RawTopList
from src.models.raw.raw_trade_cal import RawTradeCal


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
        self.equity_dividend = GenericDAO(session, EquityDividend)
        self.fund_daily_bar = GenericDAO(session, FundDailyBar)
        self.index_daily_bar = GenericDAO(session, IndexDailyBar)
        self.equity_holder_number = GenericDAO(session, EquityHolderNumber)
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
        self.raw_dividend = GenericDAO(session, RawDividend)
        self.raw_fund_daily = GenericDAO(session, RawFundDaily)
        self.raw_index_daily = GenericDAO(session, RawIndexDaily)
        self.raw_holder_number = GenericDAO(session, RawHolderNumber)
        self.raw_limit_list = GenericDAO(session, RawLimitList)
