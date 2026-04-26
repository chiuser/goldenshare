from __future__ import annotations

ALL_MARGIN_EXCHANGE_IDS = ("SSE", "SZSE", "BSE")
ALL_LIMIT_LIST_EXCHANGES = ("SH", "SZ", "BJ")
ALL_LIMIT_LIST_TYPES = ("U", "D", "Z")
ALL_LIMIT_LIST_THS_LIMIT_TYPES = ("涨停池", "连板池", "冲刺涨停", "炸板池", "跌停池")
ALL_LIMIT_LIST_THS_MARKETS = ("HS", "GEM", "STAR")
ALL_MONEYFLOW_IND_DC_CONTENT_TYPES = ("行业", "概念", "地域")
ALL_DC_BOARD_TYPES = ("行业板块", "概念板块", "地域板块")
ALL_THS_HOT_MARKETS = ("热股", "ETF", "可转债", "行业板块", "概念板块", "期货", "港股", "热基", "美股")
ALL_RANKING_IS_NEW_FLAGS = ("Y",)
ALL_DC_HOT_MARKETS = ("A股市场", "ETF基金", "港股市场", "美股市场")
ALL_DC_HOT_TYPES = ("人气榜", "飙升榜")
ALL_KPL_LIST_TAGS = ("涨停", "炸板", "跌停", "自然涨停", "竞价")
MONEYFLOW_VOLUME_FIELDS = (
    "buy_sm_vol",
    "sell_sm_vol",
    "buy_md_vol",
    "sell_md_vol",
    "buy_lg_vol",
    "sell_lg_vol",
    "buy_elg_vol",
    "sell_elg_vol",
    "net_mf_vol",
)

__all__ = [
    "ALL_MARGIN_EXCHANGE_IDS",
    "ALL_LIMIT_LIST_EXCHANGES",
    "ALL_LIMIT_LIST_TYPES",
    "ALL_LIMIT_LIST_THS_LIMIT_TYPES",
    "ALL_LIMIT_LIST_THS_MARKETS",
    "ALL_MONEYFLOW_IND_DC_CONTENT_TYPES",
    "ALL_DC_BOARD_TYPES",
    "ALL_THS_HOT_MARKETS",
    "ALL_RANKING_IS_NEW_FLAGS",
    "ALL_DC_HOT_MARKETS",
    "ALL_DC_HOT_TYPES",
    "ALL_KPL_LIST_TAGS",
    "MONEYFLOW_VOLUME_FIELDS",
]
