"""Stable column schema contracts for Dagster asset definitions."""

from orchestrator.defs.run_contracts.column_schema import ColumnContract


RAW_TUSHARE_TRADE_CALENDAR_SCHEMA = (
    ColumnContract("exchange", "VARCHAR", "交易所代码"),
    ColumnContract("cal_date", "VARCHAR", "Tushare 原始交易日，YYYYMMDD 字符串"),
    ColumnContract("is_open", "INTEGER", "Tushare 原始开市标识，1 表示开市，0 表示休市"),
    ColumnContract("pretrade_date", "VARCHAR", "上一交易日，YYYYMMDD 字符串"),
)

RAW_TUSHARE_STOCK_BASIC_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "股票代码"),
    ColumnContract("symbol", "VARCHAR", "股票简称代码"),
    ColumnContract("name", "VARCHAR", "股票名称"),
    ColumnContract("area", "VARCHAR", "地域"),
    ColumnContract("industry", "VARCHAR", "所属行业"),
    ColumnContract("fullname", "VARCHAR", "股票全称"),
    ColumnContract("enname", "VARCHAR", "英文全称"),
    ColumnContract("cnspell", "VARCHAR", "拼音缩写"),
    ColumnContract("market", "VARCHAR", "市场类型"),
    ColumnContract("exchange", "VARCHAR", "交易所代码"),
    ColumnContract("curr_type", "VARCHAR", "交易货币"),
    ColumnContract("list_status", "VARCHAR", "上市状态，沿用 Tushare 原始值"),
    ColumnContract("list_date", "VARCHAR", "上市日期，YYYYMMDD 字符串"),
    ColumnContract("delist_date", "VARCHAR", "退市日期，YYYYMMDD 字符串或空"),
    ColumnContract("is_hs", "VARCHAR", "沪深港通标识"),
    ColumnContract("act_name", "VARCHAR", "实控人名称"),
    ColumnContract("act_ent_type", "VARCHAR", "实控人企业性质"),
)

RAW_TUSHARE_NAMECHANGE_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "股票代码"),
    ColumnContract("name", "VARCHAR", "证券名称"),
    ColumnContract("start_date", "VARCHAR", "名称生效开始日期，Tushare 原始 YYYYMMDD 字符串"),
    ColumnContract("end_date", "VARCHAR", "名称生效结束日期，Tushare 原始 YYYYMMDD 字符串或空"),
    ColumnContract("ann_date", "VARCHAR", "公告日期，Tushare 原始 YYYYMMDD 字符串或空"),
    ColumnContract("change_reason", "VARCHAR", "变更原因"),
)

RAW_TUSHARE_STOCK_DAILY_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "股票代码"),
    ColumnContract("trade_date", "VARCHAR", "Tushare 原始交易日，YYYYMMDD 字符串"),
    ColumnContract("open", "DOUBLE", "当日开盘价"),
    ColumnContract("high", "DOUBLE", "当日最高价"),
    ColumnContract("low", "DOUBLE", "当日最低价"),
    ColumnContract("close", "DOUBLE", "当日收盘价"),
    ColumnContract("pre_close", "DOUBLE", "前一交易日收盘价"),
    ColumnContract("change", "DOUBLE", "源站原始变动值字段，raw 层不改名"),
    ColumnContract("pct_chg", "DOUBLE", "涨跌幅，百分比"),
    ColumnContract("vol", "DOUBLE", "成交量，沿用 Tushare 股票日线口径"),
    ColumnContract("amount", "DOUBLE", "成交额，沿用 Tushare 股票日线口径"),
)

RAW_TUSHARE_STK_NINETURN_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "Tushare 源股票代码"),
    ColumnContract("trade_date", "DATE", "Tushare 神奇九转交易日"),
    ColumnContract("freq", "VARCHAR", "九转频率，正式口径固定为 daily"),
    ColumnContract("open", "DOUBLE", "当日开盘价"),
    ColumnContract("high", "DOUBLE", "当日最高价"),
    ColumnContract("low", "DOUBLE", "当日最低价"),
    ColumnContract("close", "DOUBLE", "当日收盘价"),
    ColumnContract("vol", "DOUBLE", "成交量，沿用 Tushare 神奇九转口径"),
    ColumnContract("amount", "DOUBLE", "成交额，沿用 Tushare 神奇九转口径"),
    ColumnContract("up_count", "DOUBLE", "上九转累计计数，保留源端数值类型"),
    ColumnContract("down_count", "DOUBLE", "下九转累计计数，保留源端数值类型"),
    ColumnContract("nine_up_turn", "VARCHAR", "上九转信号，允许 +9 或空"),
    ColumnContract("nine_down_turn", "VARCHAR", "下九转信号，允许 -9 或空"),
)

RAW_STK_MINS_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "股票代码"),
    ColumnContract("freq", "INTEGER", "分钟频度，允许值为 1、5、15、30、60"),
    ColumnContract("trade_time", "TIMESTAMP", "分钟 bar 时间"),
    ColumnContract("open", "DOUBLE", "分钟 bar 开盘价"),
    ColumnContract("close", "DOUBLE", "分钟 bar 收盘价"),
    ColumnContract("high", "DOUBLE", "分钟 bar 最高价"),
    ColumnContract("low", "DOUBLE", "分钟 bar 最低价"),
    ColumnContract("vol", "BIGINT", "成交量，沿用 backup clean_next 口径"),
    ColumnContract("amount", "DOUBLE", "成交额，沿用 backup clean_next 口径"),
    ColumnContract("exchange", "VARCHAR", "交易所代码；历史全空分区归一为 VARCHAR"),
    ColumnContract("vwap", "DOUBLE", "成交均价"),
)

RAW_TUSHARE_ADJ_FACTOR_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "股票代码"),
    ColumnContract("trade_date", "VARCHAR", "Tushare 原始交易日，YYYYMMDD 字符串"),
    ColumnContract("adj_factor", "DOUBLE", "复权因子"),
)

RAW_TUSHARE_STOCK_SUSPEND_DAILY_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "股票代码"),
    ColumnContract("trade_date", "VARCHAR", "Tushare 原始交易日，YYYYMMDD 字符串"),
    ColumnContract("suspend_timing", "VARCHAR", "停牌时段，沿用 Tushare 原始字符串或空"),
    ColumnContract("suspend_type", "VARCHAR", "停复牌类型，沿用 Tushare 原始值"),
)

RAW_TUSHARE_INDEX_BASIC_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "指数代码"),
    ColumnContract("name", "VARCHAR", "指数简称"),
    ColumnContract("fullname", "VARCHAR", "指数全称"),
    ColumnContract("market", "VARCHAR", "市场或发布方市场分类"),
    ColumnContract("publisher", "VARCHAR", "发布方"),
    ColumnContract("index_type", "VARCHAR", "指数类型"),
    ColumnContract("category", "VARCHAR", "指数分类"),
    ColumnContract("base_date", "VARCHAR", "基日，YYYYMMDD 字符串"),
    ColumnContract("base_point", "DOUBLE", "基点"),
    ColumnContract("list_date", "VARCHAR", "发布日期或上市日期，YYYYMMDD 字符串"),
    ColumnContract("weight_rule", "VARCHAR", "加权方式"),
    ColumnContract("desc", "VARCHAR", "指数说明"),
    ColumnContract("exp_date", "VARCHAR", "终止日期，YYYYMMDD 字符串或空"),
)

RAW_INDEX_DAILY_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "指数代码"),
    ColumnContract("trade_date", "VARCHAR", "指数日线 raw 交易日，YYYYMMDD 字符串"),
    ColumnContract("open", "DOUBLE", "当日开盘点位"),
    ColumnContract("high", "DOUBLE", "当日最高点位"),
    ColumnContract("low", "DOUBLE", "当日最低点位"),
    ColumnContract("close", "DOUBLE", "当日收盘点位"),
    ColumnContract("pre_close", "DOUBLE", "前一交易日收盘点位"),
    ColumnContract("change", "DOUBLE", "源站原始变动值字段，raw 层不改名"),
    ColumnContract("pct_chg", "DOUBLE", "涨跌幅，百分比"),
    ColumnContract("vol", "DOUBLE", "成交量，沿用指数日线口径"),
    ColumnContract("amount", "DOUBLE", "成交额，沿用指数日线口径"),
)

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
    ColumnContract("fullname", "VARCHAR", "股票全称"),
    ColumnContract("enname", "VARCHAR", "英文全称"),
    ColumnContract("cnspell", "VARCHAR", "拼音缩写"),
    ColumnContract("market", "VARCHAR", "市场类型"),
    ColumnContract("exchange", "VARCHAR", "交易所代码"),
    ColumnContract("curr_type", "VARCHAR", "交易货币"),
    ColumnContract("list_status", "VARCHAR", "上市状态；silver 层仅保留当前上市股票"),
    ColumnContract("list_date", "DATE", "上市日期"),
    ColumnContract("delist_date", "DATE", "退市生效日期；行情有效范围不含当日"),
    ColumnContract("is_hs", "VARCHAR", "沪深港通标识"),
    ColumnContract("act_name", "VARCHAR", "实控人名称"),
    ColumnContract("act_ent_type", "VARCHAR", "实控人企业性质"),
)

SILVER_STOCK_LIFECYCLE_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "股票代码"),
    ColumnContract("symbol", "VARCHAR", "股票简称代码"),
    ColumnContract("name", "VARCHAR", "股票名称"),
    ColumnContract("exchange", "VARCHAR", "交易所代码"),
    ColumnContract("market", "VARCHAR", "市场类型；历史退市股票源站可能为空，仅作解释字段"),
    ColumnContract("curr_type", "VARCHAR", "交易货币"),
    ColumnContract("is_cny_stock", "BOOLEAN", "是否人民币计价股票"),
    ColumnContract("list_status", "VARCHAR", "上市状态，沿用 Tushare 原始值"),
    ColumnContract("list_date", "DATE", "上市日期"),
    ColumnContract("delist_date", "DATE", "退市生效日期，可为空；行情有效范围不含当日"),
)

SILVER_STOCK_IDENTITY_MAP_SCHEMA = (
    ColumnContract("latest_ts_code", "VARCHAR", "标准股票代码"),
    ColumnContract("source_ts_code", "VARCHAR", "源代码或历史代码"),
    ColumnContract("valid_from", "DATE", "映射有效起始日期"),
    ColumnContract("valid_to", "DATE", "映射失效生效日期，可为空；有效范围不含当日"),
    ColumnContract("effective_list_date", "DATE", "标准股票上市日期"),
    ColumnContract("effective_delist_date", "DATE", "标准股票退市生效日期，可为空"),
    ColumnContract("identity_source", "VARCHAR", "映射来源枚举"),
    ColumnContract("confidence", "VARCHAR", "映射置信度枚举"),
    ColumnContract("reason", "VARCHAR", "映射原因"),
    ColumnContract("created_at", "TIMESTAMP WITH TIME ZONE", "本次生成时间"),
)

SILVER_STK_MINS_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "标准股票代码"),
    ColumnContract("freq", "INTEGER", "分钟频度，允许值为 1、5、15、30、60"),
    ColumnContract("trade_date", "DATE", "交易日"),
    ColumnContract("trade_time", "TIMESTAMP", "分钟 bar 时间"),
    ColumnContract("open", "DOUBLE", "标准化分钟 bar 开盘价"),
    ColumnContract("high", "DOUBLE", "标准化分钟 bar 最高价"),
    ColumnContract("low", "DOUBLE", "标准化分钟 bar 最低价"),
    ColumnContract("close", "DOUBLE", "标准化分钟 bar 收盘价"),
    ColumnContract("vol", "DOUBLE", "标准化成交量"),
    ColumnContract("amount", "DOUBLE", "标准化成交额"),
    ColumnContract("exchange", "VARCHAR", "标准交易所代码，允许值为 SSE、SZSE、BSE"),
)

GOLD_STK_MINS_QFQ_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "标准股票代码"),
    ColumnContract(
        "freq",
        "INTEGER",
        "gold qfq 分钟频度，允许值为 1、5、15、30、60、90、120；raw/silver 源频度仍只允许 1、5、15、30、60",
    ),
    ColumnContract("trade_date", "DATE", "交易日"),
    ColumnContract("trade_time", "TIMESTAMP", "分钟 bar 时间"),
    ColumnContract("open", "DOUBLE", "前复权分钟 bar 开盘价"),
    ColumnContract("high", "DOUBLE", "前复权分钟 bar 最高价"),
    ColumnContract("low", "DOUBLE", "前复权分钟 bar 最低价"),
    ColumnContract("close", "DOUBLE", "前复权分钟 bar 收盘价"),
    ColumnContract("vol", "DOUBLE", "成交量，沿用 silver 分钟线事实"),
    ColumnContract("amount", "DOUBLE", "成交额，沿用 silver 分钟线事实"),
    ColumnContract("exchange", "VARCHAR", "标准交易所代码，沿用 silver 分钟线事实"),
)

GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "标准股票代码"),
    ColumnContract(
        "freq",
        "INTEGER",
        "gold qfq 技术指标分钟频度，允许值为 1、5、15、30、60、90、120",
    ),
    ColumnContract("trade_date", "DATE", "交易日"),
    ColumnContract("trade_time", "TIMESTAMP", "分钟 bar 时间"),
    ColumnContract("macd_dif_qfq", "DOUBLE", "MACD DIF，基于 qfq close，参数 12/26/9"),
    ColumnContract("macd_dea_qfq", "DOUBLE", "MACD DEA，基于 qfq close，参数 12/26/9"),
    ColumnContract("macd_qfq", "DOUBLE", "MACD 柱，固定为 2 * (DIF - DEA)"),
    ColumnContract("kdj_k_qfq", "DOUBLE", "KDJ K，基于 qfq high/low/close，参数 9/3/3"),
    ColumnContract("kdj_d_qfq", "DOUBLE", "KDJ D，基于 qfq high/low/close，参数 9/3/3"),
    ColumnContract("kdj_qfq", "DOUBLE", "KDJ J，固定为 3 * K - 2 * D"),
    ColumnContract("params_key", "VARCHAR", "固定参数标识，第一版为 macd_12_26_9__kdj_9_3_3"),
    ColumnContract("indicator_version", "INTEGER", "指标算法版本，第一版为 1"),
)

GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "标准股票代码"),
    ColumnContract(
        "freq",
        "INTEGER",
        "gold qfq 技术指标 state 分钟频度，允许值为 1、5、15、30、60、90、120",
    ),
    ColumnContract("trade_date", "DATE", "state 所属交易日"),
    ColumnContract("last_trade_time", "TIMESTAMP", "该股票该频度在该交易日最后一根已处理 bar"),
    ColumnContract("macd_ema_fast", "DOUBLE", "MACD 内部 fast EMA state，N=12"),
    ColumnContract("macd_ema_slow", "DOUBLE", "MACD 内部 slow EMA state，N=26"),
    ColumnContract("macd_dea", "DOUBLE", "MACD 内部 DEA state，N=9"),
    ColumnContract("kdj_k", "DOUBLE", "KDJ 下一日递推所需 K state"),
    ColumnContract("kdj_d", "DOUBLE", "KDJ 下一日递推所需 D state"),
    ColumnContract("params_key", "VARCHAR", "固定参数标识，第一版为 macd_12_26_9__kdj_9_3_3"),
    ColumnContract("indicator_version", "INTEGER", "指标算法版本，第一版为 1"),
)

SILVER_NAMECHANGE_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "股票代码"),
    ColumnContract("name", "VARCHAR", "该名称区间内实际使用的证券简称"),
    ColumnContract("start_date", "DATE", "名称变更生效日"),
    ColumnContract("end_date", "DATE", "该名称使用结束日；当前仍有效时为空"),
    ColumnContract("ann_date", "DATE", "选中这段名称变更事实的公告日期；源站为空时保留为空"),
    ColumnContract("change_reason", "VARCHAR", "变更原因"),
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

SILVER_STOCK_NINETURN_DAILY_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "标准股票代码"),
    ColumnContract("trade_date", "DATE", "交易日"),
    ColumnContract("freq", "VARCHAR", "九转频率，正式口径固定为 daily"),
    ColumnContract("open", "DOUBLE", "当日开盘价"),
    ColumnContract("high", "DOUBLE", "当日最高价"),
    ColumnContract("low", "DOUBLE", "当日最低价"),
    ColumnContract("close", "DOUBLE", "当日收盘价"),
    ColumnContract("vol", "DOUBLE", "成交量"),
    ColumnContract("amount", "DOUBLE", "成交额"),
    ColumnContract("up_count", "INTEGER", "非负上九转累计计数"),
    ColumnContract("down_count", "INTEGER", "非负下九转累计计数"),
    ColumnContract("nine_up_turn", "VARCHAR", "上九转信号，允许 +9 或空"),
    ColumnContract("nine_down_turn", "VARCHAR", "下九转信号，允许 -9 或空"),
)

SILVER_ADJ_FACTOR_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "股票代码"),
    ColumnContract("trade_date", "DATE", "交易日"),
    ColumnContract("adj_factor", "DOUBLE", "复权因子"),
)

GOLD_STOCK_DAILY_QFQ_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "股票代码"),
    ColumnContract("trade_date", "DATE", "交易日"),
    ColumnContract("open", "DOUBLE", "前复权开盘价"),
    ColumnContract("high", "DOUBLE", "前复权最高价"),
    ColumnContract("low", "DOUBLE", "前复权最低价"),
    ColumnContract("close", "DOUBLE", "前复权收盘价"),
    ColumnContract("pre_close", "DOUBLE", "前复权上一可用交易日收盘价；首个可用交易日为 0"),
    ColumnContract("change_amount", "DOUBLE", "前复权涨跌额；首个可用交易日为 0"),
    ColumnContract("pct_chg", "DOUBLE", "前复权涨跌幅，百分比；首个可用交易日为 0"),
    ColumnContract("vol", "DOUBLE", "成交量，沿用 silver_stock_daily 事实"),
    ColumnContract("amount", "DOUBLE", "成交额，沿用 silver_stock_daily 事实"),
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
    ColumnContract("down_gt_10_count", "BIGINT", "pct_chg 小于 -10% 的股票数量"),
    ColumnContract(
        "down_7_10_count",
        "BIGINT",
        "pct_chg 大于等于 -10% 且小于 -7% 的股票数量",
    ),
    ColumnContract("down_5_7_count", "BIGINT", "跌幅大于 5% 且小于等于 7% 的股票数量"),
    ColumnContract("down_3_5_count", "BIGINT", "跌幅大于 3% 且小于等于 5% 的股票数量"),
    ColumnContract("down_0_3_count", "BIGINT", "跌幅大于 0% 且小于等于 3% 的股票数量"),
    ColumnContract("flat_count", "BIGINT", "平盘股票数量，pct_chg 等于 0"),
    ColumnContract("up_0_3_count", "BIGINT", "涨幅大于 0% 且小于等于 3% 的股票数量"),
    ColumnContract("up_3_5_count", "BIGINT", "涨幅大于 3% 且小于等于 5% 的股票数量"),
    ColumnContract("up_5_7_count", "BIGINT", "涨幅大于 5% 且小于等于 7% 的股票数量"),
    ColumnContract("up_7_10_count", "BIGINT", "涨幅大于 7% 且小于等于 10% 的股票数量"),
    ColumnContract("up_gt_10_count", "BIGINT", "涨幅大于 10% 的股票数量"),
    ColumnContract("total_count", "BIGINT", "当日参与统计的股票总数"),
)

GOLD_WEALTH_MARKET_TURNOVER_SCHEMA = (
    ColumnContract("type", "VARCHAR", "主体类型，首期固定 stock"),
    ColumnContract("market", "VARCHAR", "市场标识，首期固定 CN_A"),
    ColumnContract("trade_date", "DATE", "交易日"),
    ColumnContract("freq", "SMALLINT", "分钟周期，支持 1/5/15/30/60"),
    ColumnContract("build_status", "VARCHAR", "构建状态，Lake 文件只保存 READY"),
    ColumnContract("latest_trade_time", "TIMESTAMP", "该交易日该频度内最新分钟点"),
    ColumnContract("total_amount", "DECIMAL(20,2)", "全市场成交额，单位千元"),
    ColumnContract("total_vol", "BIGINT", "全市场成交量"),
    ColumnContract("security_count", "INTEGER", "参与统计证券数"),
    ColumnContract("source_row_count", "BIGINT", "参与汇总的 silver 行数"),
    ColumnContract("points_json", "JSON", "完整分钟点数组，按 trade_time 升序"),
    ColumnContract("build_version", "VARCHAR", "构建版本，首期固定 v1"),
    ColumnContract("built_at", "TIMESTAMP WITH TIME ZONE", "本次生成时间"),
    ColumnContract("build_note", "VARCHAR", "构建说明，正常为空"),
)

CH_SHARE_FACT_MARKET_BREADTH_DAILY_SCHEMA = (
    ColumnContract("trade_date", "Date", "交易日"),
    ColumnContract("up_count", "UInt32", "当日上涨股票数量"),
    ColumnContract("down_count", "UInt32", "当日下跌股票数量"),
    ColumnContract("flat_count", "UInt32", "当日平盘股票数量"),
    ColumnContract("total_count", "UInt32", "当日参与统计的股票总数"),
    ColumnContract("red_rate", "Float64", "上涨股票数量占总数的百分比，保留两位小数"),
    ColumnContract("down_gt_10_count", "UInt32", "pct_chg 小于 -10% 的股票数量"),
    ColumnContract(
        "down_7_10_count",
        "UInt32",
        "pct_chg 大于等于 -10% 且小于 -7% 的股票数量",
    ),
    ColumnContract("down_5_7_count", "UInt32", "跌幅大于 5% 且小于等于 7% 的股票数量"),
    ColumnContract("down_3_5_count", "UInt32", "跌幅大于 3% 且小于等于 5% 的股票数量"),
    ColumnContract("down_0_3_count", "UInt32", "跌幅大于 0% 且小于等于 3% 的股票数量"),
    ColumnContract("up_0_3_count", "UInt32", "涨幅大于 0% 且小于等于 3% 的股票数量"),
    ColumnContract("up_3_5_count", "UInt32", "涨幅大于 3% 且小于等于 5% 的股票数量"),
    ColumnContract("up_5_7_count", "UInt32", "涨幅大于 5% 且小于等于 7% 的股票数量"),
    ColumnContract("up_7_10_count", "UInt32", "涨幅大于 7% 且小于等于 10% 的股票数量"),
    ColumnContract("up_gt_10_count", "UInt32", "涨幅大于 10% 的股票数量"),
    ColumnContract("updated_at", "DateTime", "ClickHouse serving 行更新时间"),
)
