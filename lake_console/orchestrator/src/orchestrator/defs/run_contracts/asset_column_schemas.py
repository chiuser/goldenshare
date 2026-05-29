"""Stable column schema contracts for Dagster asset definitions."""

from orchestrator.defs.run_contracts.column_schema import ColumnContract


SILVER_TRADE_CALENDAR_SCHEMA = (
    ColumnContract("exchange", "VARCHAR", "交易所代码"),
    ColumnContract("trade_date", "DATE", "交易日"),
    ColumnContract("is_open", "BOOLEAN", "是否开市"),
    ColumnContract("pretrade_date", "DATE", "上一交易日"),
)

SILVER_STOCK_BASIC_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "股票代码"),
    ColumnContract("symbol", "VARCHAR", "股票简称代码"),
    ColumnContract("name", "VARCHAR", "股票名称"),
    ColumnContract("area", "VARCHAR", "地域"),
    ColumnContract("industry", "VARCHAR", "所属行业"),
    ColumnContract("market", "VARCHAR", "市场类型"),
    ColumnContract("exchange", "VARCHAR", "交易所代码"),
    ColumnContract("list_status", "VARCHAR", "上市状态；silver 层仅保留当前上市股票"),
    ColumnContract("list_date", "DATE", "上市日期"),
    ColumnContract("delist_date", "DATE", "退市日期；当前上市股票通常为空"),
    ColumnContract("is_hs", "VARCHAR", "沪深港通标识"),
)

SILVER_STOCK_DAILY_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "股票代码"),
    ColumnContract("trade_date", "DATE", "交易日"),
    ColumnContract("open", "DOUBLE", "当日开盘价"),
    ColumnContract("high", "DOUBLE", "当日最高价"),
    ColumnContract("low", "DOUBLE", "当日最低价"),
    ColumnContract("close", "DOUBLE", "当日收盘价"),
    ColumnContract("pre_close", "DOUBLE", "前一交易日收盘价"),
    ColumnContract("change_amount", "DOUBLE", "收盘价相对前收盘价的变动值"),
    ColumnContract("pct_chg", "DOUBLE", "涨跌幅，百分比"),
    ColumnContract("vol", "DOUBLE", "成交量，沿用 Tushare 股票日线口径"),
    ColumnContract("amount", "DOUBLE", "成交额，沿用 Tushare 股票日线口径"),
)

SILVER_STOCK_SUSPEND_DAILY_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "股票代码"),
    ColumnContract("trade_date", "DATE", "交易日"),
    ColumnContract("suspend_timing", "VARCHAR", "停牌时段；全日停牌为空，盘中停牌记录具体时段"),
    ColumnContract("suspend_type", "VARCHAR", "停复牌类型，S 表示停牌，R 表示复牌"),
)

SILVER_INDEX_BASIC_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "指数代码"),
    ColumnContract("name", "VARCHAR", "指数简称"),
    ColumnContract("fullname", "VARCHAR", "指数全称"),
    ColumnContract("market", "VARCHAR", "市场或发布方市场分类"),
    ColumnContract("publisher", "VARCHAR", "发布方"),
    ColumnContract("index_type", "VARCHAR", "指数类型"),
    ColumnContract("category", "VARCHAR", "指数分类"),
    ColumnContract("base_date", "DATE", "基日"),
    ColumnContract("base_point", "DOUBLE", "基点"),
    ColumnContract("list_date", "DATE", "发布日期或上市日期"),
    ColumnContract("weight_rule", "VARCHAR", "加权方式"),
    ColumnContract("desc", "VARCHAR", "指数说明"),
    ColumnContract("exp_date", "DATE", "终止日期；有效指数通常为空"),
)

SILVER_INDEX_DAILY_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "指数代码"),
    ColumnContract("trade_date", "DATE", "交易日"),
    ColumnContract("open", "DOUBLE", "当日开盘点位"),
    ColumnContract("high", "DOUBLE", "当日最高点位"),
    ColumnContract("low", "DOUBLE", "当日最低点位"),
    ColumnContract("close", "DOUBLE", "当日收盘点位"),
    ColumnContract("pre_close", "DOUBLE", "前一交易日收盘点位"),
    ColumnContract("change_amount", "DOUBLE", "收盘点位相对前收盘点位的变动值"),
    ColumnContract("pct_chg", "DOUBLE", "涨跌幅，百分比"),
    ColumnContract("vol", "DOUBLE", "成交量，沿用 Tushare 指数日线口径"),
    ColumnContract("amount", "DOUBLE", "成交额，沿用 Tushare 指数日线口径"),
)

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
