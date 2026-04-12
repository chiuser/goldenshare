from __future__ import annotations

from sqlalchemy.orm import Session

from src.foundation.dao.etf_basic_dao import EtfBasicDAO
from src.foundation.dao.equity_adj_factor_dao import EquityAdjFactorDAO
from src.foundation.dao.equity_daily_bar_dao import EquityDailyBarDAO
from src.foundation.dao.equity_daily_basic_dao import EquityDailyBasicDAO
from src.foundation.dao.dividend_dao import EquityDividendDAO, RawDividendDAO
from src.foundation.dao.equity_moneyflow_dao import EquityMoneyflowDAO
from src.foundation.dao.generic import GenericDAO
from src.foundation.dao.holdernumber_dao import EquityHolderNumberDAO, RawHolderNumberDAO
from src.foundation.dao.index_basic_dao import IndexBasicDAO
from src.foundation.dao.index_daily_basic_dao import IndexDailyBasicDAO
from src.foundation.dao.index_series_active_dao import IndexSeriesActiveDAO
from src.foundation.dao.index_monthly_bar_dao import IndexMonthlyBarDAO
from src.foundation.dao.index_weight_dao import IndexWeightDAO
from src.foundation.dao.index_weekly_bar_dao import IndexWeeklyBarDAO
from src.foundation.dao.security_dao import SecurityDAO
from src.foundation.dao.stk_period_bar_adj_dao import StkPeriodBarAdjDAO
from src.foundation.dao.stk_period_bar_dao import StkPeriodBarDAO
from src.foundation.dao.sync_job_state_dao import SyncJobStateDAO
from src.foundation.dao.sync_run_log_dao import SyncRunLogDAO
from src.foundation.dao.trade_calendar_dao import TradeCalendarDAO
from src.foundation.models.core.equity_block_trade import EquityBlockTrade
from src.foundation.models.core.equity_dividend import EquityDividend
from src.foundation.models.core.equity_holder_number import EquityHolderNumber
from src.foundation.models.core.equity_limit_list import EquityLimitList
from src.foundation.models.core.equity_price_restore_factor import EquityPriceRestoreFactor
from src.foundation.models.core.equity_top_list import EquityTopList
from src.foundation.models.core.etf_basic import EtfBasic
from src.foundation.models.core.etf_index import EtfIndex
from src.foundation.models.core.fund_daily_bar import FundDailyBar
from src.foundation.models.core.fund_adj_factor import FundAdjFactor
from src.foundation.models.core.hk_security import HkSecurity
from src.foundation.models.core.dc_daily import DcDaily
from src.foundation.models.core.dc_hot import DcHot
from src.foundation.models.core.dc_index import DcIndex
from src.foundation.models.core.dc_member import DcMember
from src.foundation.models.core.index_basic import IndexBasic
from src.foundation.models.core.index_daily_basic import IndexDailyBasic
from src.foundation.models.core.index_daily_bar import IndexDailyBar
from src.foundation.models.core.index_daily_serving import IndexDailyServing
from src.foundation.models.core.index_monthly_bar import IndexMonthlyBar
from src.foundation.models.core.index_monthly_serving import IndexMonthlyServing
from src.foundation.models.core.index_weight import IndexWeight
from src.foundation.models.core.index_weekly_bar import IndexWeeklyBar
from src.foundation.models.core.index_weekly_serving import IndexWeeklyServing
from src.foundation.models.core.indicator_kdj import IndicatorKdj
from src.foundation.models.core.indicator_macd import IndicatorMacd
from src.foundation.models.core.indicator_meta import IndicatorMeta
from src.foundation.models.core.indicator_rsi import IndicatorRsi
from src.foundation.models.core.indicator_state import IndicatorState
from src.foundation.models.core.kpl_concept_cons import KplConceptCons
from src.foundation.models.core.kpl_list import KplList
from src.foundation.models.core.broker_recommend import BrokerRecommend
from src.foundation.models.core.limit_cpt_list import LimitCptList
from src.foundation.models.core.limit_list_ths import LimitListThs
from src.foundation.models.core.limit_step import LimitStep
from src.foundation.models.core.us_security import UsSecurity
from src.foundation.models.raw.raw_adj_factor import RawAdjFactor
from src.foundation.models.raw.raw_block_trade import RawBlockTrade
from src.foundation.models.raw.raw_daily import RawDaily
from src.foundation.models.raw.raw_daily_basic import RawDailyBasic
from src.foundation.models.raw.raw_dividend import RawDividend
from src.foundation.models.raw.raw_etf_basic import RawEtfBasic
from src.foundation.models.raw.raw_etf_index import RawEtfIndex
from src.foundation.models.raw.raw_fund_daily import RawFundDaily
from src.foundation.models.raw.raw_fund_adj import RawFundAdj
from src.foundation.models.raw.raw_hk_basic import RawHkBasic
from src.foundation.models.raw.raw_holdernumber import RawHolderNumber
from src.foundation.models.raw.raw_dc_daily import RawDcDaily
from src.foundation.models.raw.raw_dc_hot import RawDcHot
from src.foundation.models.raw.raw_dc_index import RawDcIndex
from src.foundation.models.raw.raw_dc_member import RawDcMember
from src.foundation.models.raw.raw_index_basic import RawIndexBasic
from src.foundation.models.raw.raw_index_daily_basic import RawIndexDailyBasic
from src.foundation.models.raw.raw_index_daily import RawIndexDaily
from src.foundation.models.raw.raw_index_monthly_bar import RawIndexMonthlyBar
from src.foundation.models.raw.raw_index_weight import RawIndexWeight
from src.foundation.models.raw.raw_index_weekly_bar import RawIndexWeeklyBar
from src.foundation.models.raw.raw_limit_list import RawLimitList
from src.foundation.models.raw.raw_limit_cpt_list import RawLimitCptList
from src.foundation.models.raw.raw_limit_list_ths import RawLimitListThs
from src.foundation.models.raw.raw_limit_step import RawLimitStep
from src.foundation.models.raw.raw_moneyflow import RawMoneyflow
from src.foundation.models.raw.raw_kpl_concept_cons import RawKplConceptCons
from src.foundation.models.raw.raw_kpl_list import RawKplList
from src.foundation.models.raw.raw_broker_recommend import RawBrokerRecommend
from src.foundation.models.raw.raw_stock_basic import RawStockBasic
from src.foundation.models.raw.raw_stk_period_bar import RawStkPeriodBar
from src.foundation.models.raw.raw_stk_period_bar_adj import RawStkPeriodBarAdj
from src.foundation.models.raw.raw_top_list import RawTopList
from src.foundation.models.raw.raw_trade_cal import RawTradeCal
from src.foundation.models.raw.raw_us_basic import RawUsBasic
from src.foundation.models.raw_multi.raw_biying_equity_adj_factor import RawBiyingEquityAdjFactor
from src.foundation.models.raw_multi.raw_biying_equity_daily_bar import RawBiyingEquityDailyBar
from src.foundation.models.raw_multi.raw_biying_equity_daily_basic import RawBiyingEquityDailyBasic
from src.foundation.models.raw_multi.raw_tushare_equity_adj_factor import RawTushareEquityAdjFactor
from src.foundation.models.raw_multi.raw_tushare_equity_daily_bar import RawTushareEquityDailyBar
from src.foundation.models.raw_multi.raw_tushare_equity_daily_basic import RawTushareEquityDailyBasic
from src.foundation.models.core.stk_period_bar import StkPeriodBar
from src.foundation.models.core.stk_period_bar_adj import StkPeriodBarAdj
from src.foundation.models.core.ths_daily import ThsDaily
from src.foundation.models.core.ths_hot import ThsHot
from src.foundation.models.core.ths_index import ThsIndex
from src.foundation.models.core.ths_member import ThsMember
from src.foundation.models.raw.raw_ths_daily import RawThsDaily
from src.foundation.models.raw.raw_ths_hot import RawThsHot
from src.foundation.models.raw.raw_ths_index import RawThsIndex
from src.foundation.models.raw.raw_ths_member import RawThsMember


class DAOFactory:
    def __init__(self, session: Session) -> None:
        self.security = SecurityDAO(session)
        self.trade_calendar = TradeCalendarDAO(session)
        self.equity_daily_bar = EquityDailyBarDAO(session)
        self.equity_adj_factor = EquityAdjFactorDAO(session)
        self.equity_price_restore_factor = GenericDAO(session, EquityPriceRestoreFactor)
        self.equity_daily_basic = EquityDailyBasicDAO(session)
        self.equity_moneyflow = EquityMoneyflowDAO(session)
        self.equity_limit_list = GenericDAO(session, EquityLimitList)
        self.equity_top_list = GenericDAO(session, EquityTopList)
        self.equity_block_trade = GenericDAO(session, EquityBlockTrade)
        self.equity_dividend = EquityDividendDAO(session)
        self.etf_basic = EtfBasicDAO(session)
        self.etf_index = GenericDAO(session, EtfIndex)
        self.hk_security = GenericDAO(session, HkSecurity)
        self.us_security = GenericDAO(session, UsSecurity)
        self.fund_daily_bar = GenericDAO(session, FundDailyBar)
        self.fund_adj_factor = GenericDAO(session, FundAdjFactor)
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
        self.indicator_meta = GenericDAO(session, IndicatorMeta)
        self.indicator_state = GenericDAO(session, IndicatorState)
        self.indicator_macd = GenericDAO(session, IndicatorMacd)
        self.indicator_kdj = GenericDAO(session, IndicatorKdj)
        self.indicator_rsi = GenericDAO(session, IndicatorRsi)
        self.ths_index = GenericDAO(session, ThsIndex)
        self.ths_member = GenericDAO(session, ThsMember)
        self.ths_daily = GenericDAO(session, ThsDaily)
        self.dc_index = GenericDAO(session, DcIndex)
        self.dc_member = GenericDAO(session, DcMember)
        self.dc_daily = GenericDAO(session, DcDaily)
        self.dc_hot = GenericDAO(session, DcHot)
        self.kpl_list = GenericDAO(session, KplList)
        self.kpl_concept_cons = GenericDAO(session, KplConceptCons)
        self.broker_recommend = GenericDAO(session, BrokerRecommend)
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
        self.raw_etf_index = GenericDAO(session, RawEtfIndex)
        self.raw_hk_basic = GenericDAO(session, RawHkBasic)
        self.raw_us_basic = GenericDAO(session, RawUsBasic)
        self.raw_fund_daily = GenericDAO(session, RawFundDaily)
        self.raw_fund_adj = GenericDAO(session, RawFundAdj)
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
        self.raw_broker_recommend = GenericDAO(session, RawBrokerRecommend)
        self.raw_limit_list_ths = GenericDAO(session, RawLimitListThs)
        self.raw_limit_step = GenericDAO(session, RawLimitStep)
        self.raw_limit_cpt_list = GenericDAO(session, RawLimitCptList)
        self.raw_holder_number = RawHolderNumberDAO(session)
        self.raw_limit_list = GenericDAO(session, RawLimitList)
        self.raw_ths_hot = GenericDAO(session, RawThsHot)
        self.raw_tushare_equity_daily_bar = GenericDAO(session, RawTushareEquityDailyBar)
        self.raw_biying_equity_daily_bar = GenericDAO(session, RawBiyingEquityDailyBar)
        self.raw_tushare_equity_adj_factor = GenericDAO(session, RawTushareEquityAdjFactor)
        self.raw_biying_equity_adj_factor = GenericDAO(session, RawBiyingEquityAdjFactor)
        self.raw_tushare_equity_daily_basic = GenericDAO(session, RawTushareEquityDailyBasic)
        self.raw_biying_equity_daily_basic = GenericDAO(session, RawBiyingEquityDailyBasic)
