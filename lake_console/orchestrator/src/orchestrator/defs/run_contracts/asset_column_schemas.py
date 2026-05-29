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

GOLD_MARKET_BREADTH_DAILY_SCHEMA = (
    ColumnContract("trade_date", "DATE", "交易日"),
    ColumnContract("up_count", "BIGINT", "当日上涨股票数量"),
    ColumnContract("down_count", "BIGINT", "当日下跌股票数量"),
    ColumnContract("flat_count", "BIGINT", "当日平盘股票数量"),
    ColumnContract("total_count", "BIGINT", "当日参与统计的股票总数"),
    ColumnContract("red_rate", "DOUBLE", "上涨股票数量占总数的百分比，保留两位小数"),
)

GOLD_STOCK_RETURN_DISTRIBUTION_SCHEMA = (
    ColumnContract("trade_date", "DATE", "交易日"),
    ColumnContract("down_gt_7_count", "BIGINT", "跌幅大于 7% 的股票数量"),
    ColumnContract("down_5_7_count", "BIGINT", "跌幅大于 5% 且小于等于 7% 的股票数量"),
    ColumnContract("down_3_5_count", "BIGINT", "跌幅大于 3% 且小于等于 5% 的股票数量"),
    ColumnContract("down_0_3_count", "BIGINT", "跌幅大于 0% 且小于等于 3% 的股票数量"),
    ColumnContract("flat_count", "BIGINT", "平盘股票数量，pct_chg 等于 0"),
    ColumnContract("up_0_3_count", "BIGINT", "涨幅大于 0% 且小于等于 3% 的股票数量"),
    ColumnContract("up_3_5_count", "BIGINT", "涨幅大于 3% 且小于等于 5% 的股票数量"),
    ColumnContract("up_5_7_count", "BIGINT", "涨幅大于 5% 且小于等于 7% 的股票数量"),
    ColumnContract("up_gt_7_count", "BIGINT", "涨幅大于 7% 的股票数量"),
    ColumnContract("total_count", "BIGINT", "当日参与统计的股票总数"),
)

CH_SHARE_FACT_MARKET_BREADTH_DAILY_SCHEMA = (
    ColumnContract("trade_date", "Date", "交易日"),
    ColumnContract("up_count", "UInt32", "当日上涨股票数量"),
    ColumnContract("down_count", "UInt32", "当日下跌股票数量"),
    ColumnContract("flat_count", "UInt32", "当日平盘股票数量"),
    ColumnContract("total_count", "UInt32", "当日参与统计的股票总数"),
    ColumnContract("red_rate", "Float64", "上涨股票数量占总数的百分比，保留两位小数"),
    ColumnContract("down_gt_7_count", "UInt32", "跌幅大于 7% 的股票数量"),
    ColumnContract("down_5_7_count", "UInt32", "跌幅大于 5% 且小于等于 7% 的股票数量"),
    ColumnContract("down_3_5_count", "UInt32", "跌幅大于 3% 且小于等于 5% 的股票数量"),
    ColumnContract("down_0_3_count", "UInt32", "跌幅大于 0% 且小于等于 3% 的股票数量"),
    ColumnContract("up_0_3_count", "UInt32", "涨幅大于 0% 且小于等于 3% 的股票数量"),
    ColumnContract("up_3_5_count", "UInt32", "涨幅大于 3% 且小于等于 5% 的股票数量"),
    ColumnContract("up_5_7_count", "UInt32", "涨幅大于 5% 且小于等于 7% 的股票数量"),
    ColumnContract("up_gt_7_count", "UInt32", "涨幅大于 7% 的股票数量"),
    ColumnContract("updated_at", "DateTime", "ClickHouse serving 行更新时间"),
)
