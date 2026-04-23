from __future__ import annotations

from src.foundation.services.sync_v2.dataset_strategies.adj_factor import build_adj_factor_units
from src.foundation.services.sync_v2.dataset_strategies.biying_equity_daily import build_biying_equity_daily_units
from src.foundation.services.sync_v2.dataset_strategies.biying_moneyflow import build_biying_moneyflow_units
from src.foundation.services.sync_v2.dataset_strategies.block_trade import build_block_trade_units
from src.foundation.services.sync_v2.dataset_strategies.broker_recommend import build_broker_recommend_units
from src.foundation.services.sync_v2.dataset_strategies.cyq_perf import build_cyq_perf_units
from src.foundation.services.sync_v2.dataset_strategies.daily import build_daily_units
from src.foundation.services.sync_v2.dataset_strategies.daily_basic import build_daily_basic_units
from src.foundation.services.sync_v2.dataset_strategies.dc_daily import build_dc_daily_units
from src.foundation.services.sync_v2.dataset_strategies.dc_hot import build_dc_hot_units
from src.foundation.services.sync_v2.dataset_strategies.dc_index import build_dc_index_units
from src.foundation.services.sync_v2.dataset_strategies.dc_member import build_dc_member_units
from src.foundation.services.sync_v2.dataset_strategies.dividend import build_dividend_units
from src.foundation.services.sync_v2.dataset_strategies.etf_basic import build_etf_basic_units
from src.foundation.services.sync_v2.dataset_strategies.etf_index import build_etf_index_units
from src.foundation.services.sync_v2.dataset_strategies.fund_adj import build_fund_adj_units
from src.foundation.services.sync_v2.dataset_strategies.fund_daily import build_fund_daily_units
from src.foundation.services.sync_v2.dataset_strategies.hk_basic import build_hk_basic_units
from src.foundation.services.sync_v2.dataset_strategies.index_basic import build_index_basic_units
from src.foundation.services.sync_v2.dataset_strategies.index_daily import build_index_daily_units
from src.foundation.services.sync_v2.dataset_strategies.index_daily_basic import build_index_daily_basic_units
from src.foundation.services.sync_v2.dataset_strategies.index_monthly import build_index_monthly_units
from src.foundation.services.sync_v2.dataset_strategies.index_weekly import build_index_weekly_units
from src.foundation.services.sync_v2.dataset_strategies.index_weight import build_index_weight_units
from src.foundation.services.sync_v2.dataset_strategies.kpl_concept_cons import build_kpl_concept_cons_units
from src.foundation.services.sync_v2.dataset_strategies.kpl_list import build_kpl_list_units
from src.foundation.services.sync_v2.dataset_strategies.limit_cpt_list import build_limit_cpt_list_units
from src.foundation.services.sync_v2.dataset_strategies.limit_list_d import build_limit_list_d_units
from src.foundation.services.sync_v2.dataset_strategies.limit_list_ths import build_limit_list_ths_units
from src.foundation.services.sync_v2.dataset_strategies.limit_step import build_limit_step_units
from src.foundation.services.sync_v2.dataset_strategies.margin import build_margin_units
from src.foundation.services.sync_v2.dataset_strategies.moneyflow import build_moneyflow_units
from src.foundation.services.sync_v2.dataset_strategies.moneyflow_cnt_ths import build_moneyflow_cnt_ths_units
from src.foundation.services.sync_v2.dataset_strategies.moneyflow_dc import build_moneyflow_dc_units
from src.foundation.services.sync_v2.dataset_strategies.moneyflow_ind_dc import build_moneyflow_ind_dc_units
from src.foundation.services.sync_v2.dataset_strategies.moneyflow_ind_ths import build_moneyflow_ind_ths_units
from src.foundation.services.sync_v2.dataset_strategies.moneyflow_mkt_dc import build_moneyflow_mkt_dc_units
from src.foundation.services.sync_v2.dataset_strategies.moneyflow_ths import build_moneyflow_ths_units
from src.foundation.services.sync_v2.dataset_strategies.stk_limit import build_stk_limit_units
from src.foundation.services.sync_v2.dataset_strategies.stk_nineturn import build_stk_nineturn_units
from src.foundation.services.sync_v2.dataset_strategies.stk_holdernumber import build_stk_holdernumber_units
from src.foundation.services.sync_v2.dataset_strategies.stk_factor_pro import build_stk_factor_pro_units
from src.foundation.services.sync_v2.dataset_strategies.stk_period_bar_adj_month import (
    build_stk_period_bar_adj_month_units,
)
from src.foundation.services.sync_v2.dataset_strategies.stk_period_bar_adj_week import (
    build_stk_period_bar_adj_week_units,
)
from src.foundation.services.sync_v2.dataset_strategies.stk_period_bar_month import build_stk_period_bar_month_units
from src.foundation.services.sync_v2.dataset_strategies.stk_period_bar_week import build_stk_period_bar_week_units
from src.foundation.services.sync_v2.dataset_strategies.stock_st import build_stock_st_units
from src.foundation.services.sync_v2.dataset_strategies.stock_basic import build_stock_basic_units
from src.foundation.services.sync_v2.dataset_strategies.suspend_d import build_suspend_d_units
from src.foundation.services.sync_v2.dataset_strategies.ths_daily import build_ths_daily_units
from src.foundation.services.sync_v2.dataset_strategies.ths_hot import build_ths_hot_units
from src.foundation.services.sync_v2.dataset_strategies.ths_index import build_ths_index_units
from src.foundation.services.sync_v2.dataset_strategies.ths_member import build_ths_member_units
from src.foundation.services.sync_v2.dataset_strategies.top_list import build_top_list_units
from src.foundation.services.sync_v2.dataset_strategies.trade_cal import build_trade_cal_units
from src.foundation.services.sync_v2.dataset_strategies.us_basic import build_us_basic_units

DATASET_STRATEGY_REGISTRY = {
    "adj_factor": build_adj_factor_units,
    "biying_equity_daily": build_biying_equity_daily_units,
    "biying_moneyflow": build_biying_moneyflow_units,
    "block_trade": build_block_trade_units,
    "broker_recommend": build_broker_recommend_units,
    "cyq_perf": build_cyq_perf_units,
    "daily": build_daily_units,
    "daily_basic": build_daily_basic_units,
    "dc_daily": build_dc_daily_units,
    "dc_hot": build_dc_hot_units,
    "dc_index": build_dc_index_units,
    "dc_member": build_dc_member_units,
    "dividend": build_dividend_units,
    "etf_basic": build_etf_basic_units,
    "etf_index": build_etf_index_units,
    "fund_adj": build_fund_adj_units,
    "fund_daily": build_fund_daily_units,
    "hk_basic": build_hk_basic_units,
    "index_basic": build_index_basic_units,
    "index_daily": build_index_daily_units,
    "index_daily_basic": build_index_daily_basic_units,
    "index_monthly": build_index_monthly_units,
    "index_weekly": build_index_weekly_units,
    "index_weight": build_index_weight_units,
    "kpl_concept_cons": build_kpl_concept_cons_units,
    "kpl_list": build_kpl_list_units,
    "limit_cpt_list": build_limit_cpt_list_units,
    "limit_list_d": build_limit_list_d_units,
    "limit_list_ths": build_limit_list_ths_units,
    "limit_step": build_limit_step_units,
    "margin": build_margin_units,
    "moneyflow": build_moneyflow_units,
    "moneyflow_cnt_ths": build_moneyflow_cnt_ths_units,
    "moneyflow_dc": build_moneyflow_dc_units,
    "moneyflow_ind_dc": build_moneyflow_ind_dc_units,
    "moneyflow_ind_ths": build_moneyflow_ind_ths_units,
    "moneyflow_mkt_dc": build_moneyflow_mkt_dc_units,
    "moneyflow_ths": build_moneyflow_ths_units,
    "stk_limit": build_stk_limit_units,
    "stk_nineturn": build_stk_nineturn_units,
    "stk_holdernumber": build_stk_holdernumber_units,
    "stk_factor_pro": build_stk_factor_pro_units,
    "stk_period_bar_adj_month": build_stk_period_bar_adj_month_units,
    "stk_period_bar_adj_week": build_stk_period_bar_adj_week_units,
    "stk_period_bar_month": build_stk_period_bar_month_units,
    "stk_period_bar_week": build_stk_period_bar_week_units,
    "stock_st": build_stock_st_units,
    "stock_basic": build_stock_basic_units,
    "suspend_d": build_suspend_d_units,
    "ths_daily": build_ths_daily_units,
    "ths_hot": build_ths_hot_units,
    "ths_index": build_ths_index_units,
    "ths_member": build_ths_member_units,
    "top_list": build_top_list_units,
    "trade_cal": build_trade_cal_units,
    "us_basic": build_us_basic_units,
}


def get_dataset_strategy(dataset_key: str):
    return DATASET_STRATEGY_REGISTRY.get(dataset_key)


__all__ = ["DATASET_STRATEGY_REGISTRY", "get_dataset_strategy"]
