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
from src.dao.index_series_active_dao import IndexSeriesActiveDAO
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
from src.models.core.hk_security import HkSecurity
from src.models.core.dc_daily import DcDaily
from src.models.core.dc_hot import DcHot
from src.models.core.dc_index import DcIndex
from src.models.core.dc_member import DcMember
from src.models.core.index_basic import IndexBasic
from src.models.core.index_daily_basic import IndexDailyBasic
from src.models.core.index_daily_bar import IndexDailyBar
from src.models.core.index_daily_serving import IndexDailyServing
from src.models.core.index_monthly_bar import IndexMonthlyBar
from src.models.core.index_monthly_serving import IndexMonthlyServing
from src.models.core.index_weight import IndexWeight
from src.models.core.index_weekly_bar import IndexWeeklyBar
from src.models.core.index_weekly_serving import IndexWeeklyServing
from src.models.core.kpl_concept_cons import KplConceptCons
from src.models.core.kpl_list import KplList
from src.models.core.limit_cpt_list import LimitCptList
from src.models.core.limit_list_ths import LimitListThs
from src.models.core.limit_step import LimitStep
from src.models.core.us_security import UsSecurity
from src.models.raw.raw_adj_factor import RawAdjFactor
from src.models.raw.raw_block_trade import RawBlockTrade
from src.models.raw.raw_daily import RawDaily
from src.models.raw.raw_daily_basic import RawDailyBasic
from src.models.raw.raw_dividend import RawDividend
from src.models.raw.raw_etf_basic import RawEtfBasic
from src.models.raw.raw_fund_daily import RawFundDaily
from src.models.raw.raw_hk_basic import RawHkBasic
from src.models.raw.raw_holdernumber import RawHolderNumber
from src.models.raw.raw_dc_daily import RawDcDaily
from src.models.raw.raw_dc_hot import RawDcHot
from src.models.raw.raw_dc_index import RawDcIndex
from src.models.raw.raw_dc_member import RawDcMember
from src.models.raw.raw_index_basic import RawIndexBasic
from src.models.raw.raw_index_daily_basic import RawIndexDailyBasic
from src.models.raw.raw_index_daily import RawIndexDaily
from src.models.raw.raw_index_monthly_bar import RawIndexMonthlyBar
from src.models.raw.raw_index_weight import RawIndexWeight
from src.models.raw.raw_index_weekly_bar import RawIndexWeeklyBar
from src.models.raw.raw_limit_list import RawLimitList
from src.models.raw.raw_limit_cpt_list import RawLimitCptList
from src.models.raw.raw_limit_list_ths import RawLimitListThs
from src.models.raw.raw_limit_step import RawLimitStep
from src.models.raw.raw_moneyflow import RawMoneyflow
from src.models.raw.raw_kpl_concept_cons import RawKplConceptCons
from src.models.raw.raw_kpl_list import RawKplList
from src.models.raw.raw_stock_basic import RawStockBasic
from src.models.raw.raw_stk_period_bar import RawStkPeriodBar
from src.models.raw.raw_stk_period_bar_adj import RawStkPeriodBarAdj
from src.models.raw.raw_top_list import RawTopList
from src.models.raw.raw_trade_cal import RawTradeCal
from src.models.raw.raw_us_basic import RawUsBasic
from src.models.core.stk_period_bar import StkPeriodBar
from src.models.core.stk_period_bar_adj import StkPeriodBarAdj
from src.models.core.ths_daily import ThsDaily
from src.models.core.ths_hot import ThsHot
from src.models.core.ths_index import ThsIndex
from src.models.core.ths_member import ThsMember
from src.models.raw.raw_ths_daily import RawThsDaily
from src.models.raw.raw_ths_hot import RawThsHot
from src.models.raw.raw_ths_index import RawThsIndex
from src.models.raw.raw_ths_member import RawThsMember


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
        self.hk_security = GenericDAO(session, HkSecurity)
        self.us_security = GenericDAO(session, UsSecurity)
        self.fund_daily_bar = GenericDAO(session, FundDailyBar)
        self.stk_period_bar = StkPeriodBarDAO(session)
        self.stk_period_bar_adj = StkPeriodBarAdjDAO(session)
        self.index_basic = IndexBasicDAO(session)
        self.index_daily_bar = GenericDAO(session, IndexDailyBar)
        self.index_daily_serving = GenericDAO(session, IndexDailyServing)
        self.index_weekly_bar = IndexWeeklyBarDAO(session)
        self.index_weekly_serving = GenericDAO(session, IndexWeeklyServing)
        self.index_monthly_bar = IndexMonthlyBarDAO(session)
        self.index_monthly_serving = GenericDAO(session, IndexMonthlyServing)
        self.index_weight = IndexWeightDAO(session)
        self.index_daily_basic = IndexDailyBasicDAO(session)
        self.ths_index = GenericDAO(session, ThsIndex)
        self.ths_member = GenericDAO(session, ThsMember)
        self.ths_daily = GenericDAO(session, ThsDaily)
        self.dc_index = GenericDAO(session, DcIndex)
        self.dc_member = GenericDAO(session, DcMember)
        self.dc_daily = GenericDAO(session, DcDaily)
        self.dc_hot = GenericDAO(session, DcHot)
        self.kpl_list = GenericDAO(session, KplList)
        self.kpl_concept_cons = GenericDAO(session, KplConceptCons)
        self.limit_list_ths = GenericDAO(session, LimitListThs)
        self.limit_step = GenericDAO(session, LimitStep)
        self.limit_cpt_list = GenericDAO(session, LimitCptList)
        self.ths_hot = GenericDAO(session, ThsHot)
        self.equity_holder_number = EquityHolderNumberDAO(session)
        self.sync_job_state = SyncJobStateDAO(session)
        self.sync_run_log = SyncRunLogDAO(session)
        self.index_series_active = IndexSeriesActiveDAO(session)

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
        self.raw_hk_basic = GenericDAO(session, RawHkBasic)
        self.raw_us_basic = GenericDAO(session, RawUsBasic)
        self.raw_fund_daily = GenericDAO(session, RawFundDaily)
        self.raw_stk_period_bar = GenericDAO(session, RawStkPeriodBar)
        self.raw_stk_period_bar_adj = GenericDAO(session, RawStkPeriodBarAdj)
        self.raw_index_basic = GenericDAO(session, RawIndexBasic)
        self.raw_index_daily = GenericDAO(session, RawIndexDaily)
        self.raw_index_weekly_bar = GenericDAO(session, RawIndexWeeklyBar)
        self.raw_index_monthly_bar = GenericDAO(session, RawIndexMonthlyBar)
        self.raw_index_weight = GenericDAO(session, RawIndexWeight)
        self.raw_index_daily_basic = GenericDAO(session, RawIndexDailyBasic)
        self.raw_ths_index = GenericDAO(session, RawThsIndex)
        self.raw_ths_member = GenericDAO(session, RawThsMember)
        self.raw_ths_daily = GenericDAO(session, RawThsDaily)
        self.raw_dc_index = GenericDAO(session, RawDcIndex)
        self.raw_dc_member = GenericDAO(session, RawDcMember)
        self.raw_dc_daily = GenericDAO(session, RawDcDaily)
        self.raw_dc_hot = GenericDAO(session, RawDcHot)
        self.raw_kpl_list = GenericDAO(session, RawKplList)
        self.raw_kpl_concept_cons = GenericDAO(session, RawKplConceptCons)
        self.raw_limit_list_ths = GenericDAO(session, RawLimitListThs)
        self.raw_limit_step = GenericDAO(session, RawLimitStep)
        self.raw_limit_cpt_list = GenericDAO(session, RawLimitCptList)
        self.raw_holder_number = RawHolderNumberDAO(session)
        self.raw_limit_list = GenericDAO(session, RawLimitList)
        self.raw_ths_hot = GenericDAO(session, RawThsHot)
