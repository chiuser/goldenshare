from __future__ import annotations

STOCK_BASIC_FIELDS = (
    "ts_code",
    "symbol",
    "name",
    "area",
    "industry",
    "fullname",
    "enname",
    "cnspell",
    "market",
    "exchange",
    "curr_type",
    "list_status",
    "list_date",
    "delist_date",
    "is_hs",
    "act_name",
    "act_ent_type",
)

TRADE_CAL_FIELDS = (
    "exchange",
    "cal_date",
    "is_open",
    "pretrade_date",
)

STK_MINS_SOURCE_FIELDS = (
    "ts_code",
    "trade_time",
    "open",
    "close",
    "high",
    "low",
    "vol",
    "amount",
    "freq",
    "exchange",
    "vwap",
)

STK_MINS_FIELDS = (
    "ts_code",
    "freq",
    "trade_time",
    "open",
    "close",
    "high",
    "low",
    "vol",
    "amount",
    "exchange",
    "vwap",
)

STK_MINS_ALLOWED_FREQS = {1, 5, 15, 30, 60}
