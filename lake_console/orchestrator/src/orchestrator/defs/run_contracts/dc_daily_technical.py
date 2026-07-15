"""Stable contracts for daily Eastmoney board technical indicators."""

DC_DAILY_TECHNICAL_HISTORY_START_DATE = "2024-01-02"
DC_DAILY_TECHNICAL_MA_PERIODS = (5, 10, 15, 20, 30, 60, 120, 250)
DC_DAILY_TECHNICAL_MACD = (12, 26, 9)
DC_DAILY_TECHNICAL_KDJ = (9, 3, 3)
DC_DAILY_TECHNICAL_BOLL = (20, 2)
DC_DAILY_TECHNICAL_BOLL_STD_DDOF = 0
DC_DAILY_TECHNICAL_SENSOR_WINDOW_LIMIT = 10
DC_DAILY_TECHNICAL_INDICATOR_VERSION = "v1"

DC_DAILY_TECHNICAL_INPUT_COLUMNS = (
    "ts_code",
    "trade_date",
    "category",
    "close",
    "high",
    "low",
)
DC_DAILY_TECHNICAL_CHECKS = ("gold_dc_daily_technical_core_check",)

DC_DAILY_TECHNICAL_PARAMS_KEY = (
    "ma_5_10_15_20_30_60_120_250__"
    "macd_12_26_9__"
    "kdj_9_3_3__"
    "boll_20_2"
)
