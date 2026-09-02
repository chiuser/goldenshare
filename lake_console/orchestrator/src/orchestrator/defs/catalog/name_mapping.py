"""Stable Chinese display names for dataset identifiers."""

from types import MappingProxyType

DATASET_CHINESE_NAMES = MappingProxyType(
    {
        "stock_basic": "股票基础信息",
        "stock_lifecycle": "股票生命周期",
        "namechange": "股票曾用名",
        "trade_cal": "交易日历",
        "daily": "A股日线行情",
        "stk_nineturn": "神奇九转",
        "stock_nineturn_daily": "股票日线神奇九转",
        "adj_factor": "复权因子",
        "stock_daily_qfq": "股票日线前复权",
        "stock_daily_trend_channel": "股票日线前复权趋势通道",
        "stock_daily_trend_channel_state": "股票日线前复权趋势通道状态",
        "stock_daily_qfq_nineturn": "股票日线前复权九转",
        "stk_mins": "股票分钟线",
        "stk_mins_qfq": "股票分钟线前复权",
        "stk_mins_qfq_nineturn": "股票分钟线前复权九转",
        "stk_mins_qfq_macd_kdj": "股票分钟线前复权 MACD/KDJ",
        "stk_mins_qfq_macd_kdj_state": "股票分钟线前复权 MACD/KDJ State",
        "stock_identity_map": "股票身份映射",
        "suspend_d": "每日停复牌信息",
        "index_basic": "指数基本信息",
        "index_daily": "指数日线行情",
        "index_mins": "指数历史分钟行情",
        "etf_basic": "ETF 基础信息",
        "fund_daily": "基金日线行情",
        "etf_daily": "ETF 日线行情",
        "fund_adj": "基金复权因子",
        "etf_adj_factor": "ETF 复权因子",
        "etf_mins": "ETF 历史分钟行情",
        "major_index_mins": "主要指数分钟线",
        "major_index_daily_nineturn": "主要指数日线九转",
        "major_index_mins_nineturn": "主要指数分钟九转",
        "idx_factor_pro": "指数技术因子（专业版）",
        "index_factor_pro": "指数技术因子（专业版）标准层",
        "major_index_mins_technical": "主要指数分钟技术指标",
        "major_index_mins_technical_state": "主要指数分钟技术指标状态",
        "index_global": "国际指数日线",
        "dc_index": "东方财富板块分类",
        "dc_industry_hierarchy": "东方财富行业层级",
        "dc_member": "东方财富板块成分",
        "dc_daily": "东方财富板块行情",
        "dc_daily_technical": "板块日线技术指标",
        "market_major_indices": "主要指数名单",
        "market_major_indices_daily": "主要指数日线",
        "market_breadth": "市场宽度",
        "stock_return_distribution": "股票涨跌幅分布",
        "wealth_market_turnover": "财富市场成交额快照",
        "ch_share_fact_market_breadth_daily": "ClickHouse 市场宽度日表",
        "prod_ch_share_fact_market_breadth_daily": "Prod ClickHouse 市场宽度日表",
        "ch_dc_daily_technical": "ClickHouse 板块日线技术指标表",
        "prod_ch_dc_daily_technical": "Prod ClickHouse 板块日线技术指标表",
        "lake_root_health": "Lake 根目录健康",
    }
)


def get_dataset_chinese_name(dataset_id: str) -> str:
    """Return the registered Chinese display name for a stable dataset id."""

    try:
        return DATASET_CHINESE_NAMES[dataset_id]
    except KeyError as error:
        raise KeyError(
            f"Unknown dataset id for Chinese name mapping: {dataset_id!r}"
        ) from error
