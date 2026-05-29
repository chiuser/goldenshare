"""Stable column schema contracts for Dagster asset definitions."""

from orchestrator.defs.run_contracts.column_schema import ColumnContract


GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA = (
    ColumnContract("trade_date", "DATE", "交易日"),
    ColumnContract(
        "rank",
        "INTEGER",
        "主要指数展示顺序，来自 seed 固定排序；历史早期可能不连续",
    ),
    ColumnContract("ts_code", "VARCHAR", "指数代码"),
    ColumnContract("display_name", "VARCHAR", "指数展示名称"),
    ColumnContract("open", "DOUBLE", "当日开盘点位"),
    ColumnContract("high", "DOUBLE", "当日最高点位"),
    ColumnContract("low", "DOUBLE", "当日最低点位"),
    ColumnContract("close", "DOUBLE", "当日收盘点位"),
    ColumnContract("pre_close", "DOUBLE", "前一交易日收盘点位"),
    ColumnContract("change_amount", "DOUBLE", "收盘点位相对前收盘点位的变动值"),
    ColumnContract("pct_chg", "DOUBLE", "涨跌幅，百分比"),
    ColumnContract("vol", "DOUBLE", "成交量，沿用 silver_index_daily / Tushare 指数日线口径"),
    ColumnContract(
        "amount",
        "DOUBLE",
        "成交额，沿用 silver_index_daily / Tushare 指数日线口径",
    ),
)
