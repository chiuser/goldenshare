from __future__ import annotations

from dataclasses import dataclass


OPS_DATASET_DEFAULT_VIEW_KEY = "ops_dataset_default"


@dataclass(frozen=True, slots=True)
class DatasetCatalogGroup:
    group_key: str
    group_label: str
    group_order: int
    description: str = ""


@dataclass(frozen=True, slots=True)
class DatasetCatalogItem:
    dataset_key: str
    group_key: str
    item_order: int
    visible: bool = True


@dataclass(frozen=True, slots=True)
class DatasetCatalogView:
    view_key: str
    groups: tuple[DatasetCatalogGroup, ...]
    items: tuple[DatasetCatalogItem, ...]


OPS_DATASET_DEFAULT_VIEW = DatasetCatalogView(
    view_key=OPS_DATASET_DEFAULT_VIEW_KEY,
    groups=(
        DatasetCatalogGroup("reference_data", "A股基础数据", 1),
        DatasetCatalogGroup("equity_market", "A股行情", 2),
        DatasetCatalogGroup("board_theme", "板块 / 题材", 3),
        DatasetCatalogGroup("leader_board", "榜单", 4),
        DatasetCatalogGroup("limit_board", "涨跌停榜", 5),
        DatasetCatalogGroup("index_market_data", "A股指数行情", 6),
        DatasetCatalogGroup("etf_fund", "ETF基金", 7),
        DatasetCatalogGroup("moneyflow", "资金流向", 8),
        DatasetCatalogGroup("broker_recommendation", "券商推荐", 9),
        DatasetCatalogGroup("news", "新闻资讯", 10),
        DatasetCatalogGroup("hk_reference_data", "港股基础数据", 11),
        DatasetCatalogGroup("us_reference_data", "美股基础数据", 12),
        DatasetCatalogGroup("technical_indicators", "技术指标", 13),
    ),
    items=(
        DatasetCatalogItem("stock_basic", "reference_data", 10),
        DatasetCatalogItem("stock_st", "reference_data", 20),
        DatasetCatalogItem("suspend_d", "reference_data", 30),
        DatasetCatalogItem("stk_limit", "reference_data", 40),
        DatasetCatalogItem("index_basic", "reference_data", 50),
        DatasetCatalogItem("index_weight", "reference_data", 60),
        DatasetCatalogItem("dividend", "reference_data", 70),
        DatasetCatalogItem("stk_holdernumber", "reference_data", 80),
        DatasetCatalogItem("etf_basic", "reference_data", 90),
        DatasetCatalogItem("trade_cal", "reference_data", 100),
        DatasetCatalogItem("biying_equity_daily", "equity_market", 10),
        DatasetCatalogItem("adj_factor", "equity_market", 20),
        DatasetCatalogItem("block_trade", "equity_market", 30),
        DatasetCatalogItem("daily_basic", "equity_market", 40),
        DatasetCatalogItem("stk_mins", "equity_market", 50),
        DatasetCatalogItem("stk_period_bar_week", "equity_market", 60),
        DatasetCatalogItem("stk_period_bar_adj_week", "equity_market", 70),
        DatasetCatalogItem("daily", "equity_market", 80),
        DatasetCatalogItem("stk_period_bar_month", "equity_market", 90),
        DatasetCatalogItem("stk_period_bar_adj_month", "equity_market", 100),
        DatasetCatalogItem("margin", "equity_market", 110),
        DatasetCatalogItem("top_list", "equity_market", 120),
        DatasetCatalogItem("dc_index", "board_theme", 10),
        DatasetCatalogItem("dc_member", "board_theme", 20),
        DatasetCatalogItem("dc_daily", "board_theme", 30),
        DatasetCatalogItem("ths_index", "board_theme", 40),
        DatasetCatalogItem("ths_member", "board_theme", 50),
        DatasetCatalogItem("ths_daily", "board_theme", 60),
        DatasetCatalogItem("kpl_concept_cons", "board_theme", 70),
        DatasetCatalogItem("dc_hot", "leader_board", 10),
        DatasetCatalogItem("ths_hot", "leader_board", 20),
        DatasetCatalogItem("kpl_list", "leader_board", 30),
        DatasetCatalogItem("limit_list_ths", "limit_board", 10),
        DatasetCatalogItem("limit_list_d", "limit_board", 20),
        DatasetCatalogItem("limit_cpt_list", "limit_board", 30),
        DatasetCatalogItem("limit_step", "limit_board", 40),
        DatasetCatalogItem("index_weekly", "index_market_data", 10),
        DatasetCatalogItem("index_daily", "index_market_data", 20),
        DatasetCatalogItem("index_monthly", "index_market_data", 30),
        DatasetCatalogItem("index_daily_basic", "index_market_data", 40),
        DatasetCatalogItem("etf_index", "etf_fund", 10),
        DatasetCatalogItem("fund_adj", "etf_fund", 20),
        DatasetCatalogItem("fund_daily", "etf_fund", 30),
        DatasetCatalogItem("biying_moneyflow", "moneyflow", 10),
        DatasetCatalogItem("moneyflow", "moneyflow", 20),
        DatasetCatalogItem("moneyflow_dc", "moneyflow", 30),
        DatasetCatalogItem("moneyflow_ths", "moneyflow", 40),
        DatasetCatalogItem("moneyflow_mkt_dc", "moneyflow", 50),
        DatasetCatalogItem("moneyflow_ind_dc", "moneyflow", 60),
        DatasetCatalogItem("moneyflow_cnt_ths", "moneyflow", 70),
        DatasetCatalogItem("moneyflow_ind_ths", "moneyflow", 80),
        DatasetCatalogItem("broker_recommend", "broker_recommendation", 10),
        DatasetCatalogItem("cctv_news", "news", 10),
        DatasetCatalogItem("major_news", "news", 20),
        DatasetCatalogItem("hk_basic", "hk_reference_data", 10),
        DatasetCatalogItem("us_basic", "us_reference_data", 10),
        DatasetCatalogItem("cyq_perf", "technical_indicators", 10),
        DatasetCatalogItem("stk_nineturn", "technical_indicators", 20),
        DatasetCatalogItem("stk_factor_pro", "technical_indicators", 30),
    ),
)
