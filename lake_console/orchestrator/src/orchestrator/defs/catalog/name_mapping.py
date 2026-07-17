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
        "stk_mins": "股票分钟线",
        "stk_mins_qfq": "股票分钟线前复权",
        "stk_mins_qfq_macd_kdj": "股票分钟线前复权 MACD/KDJ",
        "stk_mins_qfq_macd_kdj_state": "股票分钟线前复权 MACD/KDJ State",
        "stock_identity_map": "股票身份映射",
        "suspend_d": "每日停复牌信息",
        "index_basic": "指数基本信息",
        "index_daily": "指数日线行情",
        "dc_index": "东方财富板块分类",
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
        raise KeyError(f"Unknown dataset id for Chinese name mapping: {dataset_id!r}") from error
