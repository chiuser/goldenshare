from __future__ import annotations

ALL_MARGIN_EXCHANGE_IDS = ("SSE", "SZSE", "BSE")
ALL_LIMIT_LIST_EXCHANGES = ("SH", "SZ", "BJ")
ALL_LIMIT_LIST_TYPES = ("U", "D", "Z")
ALL_MONEYFLOW_IND_DC_CONTENT_TYPES = ("行业", "概念", "地域")
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
    "ALL_MONEYFLOW_IND_DC_CONTENT_TYPES",
    "MONEYFLOW_VOLUME_FIELDS",
]
