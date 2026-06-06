"""Stable Chinese display names for dataset identifiers."""

from types import MappingProxyType


DATASET_CHINESE_NAMES = MappingProxyType(
    {
        "stock_basic": "股票基础信息",
        "namechange": "股票曾用名",
        "trade_cal": "交易日历",
        "daily": "A股日线行情",
        "adj_factor": "复权因子",
        "stk_mins": "股票分钟线",
        "stk_mins_qfq": "股票分钟线前复权",
        "stock_identity_map": "股票身份映射",
        "suspend_d": "每日停复牌信息",
        "index_basic": "指数基本信息",
        "index_daily": "指数日线行情",
        "market_major_indices": "主要指数名单",
        "market_major_indices_daily": "主要指数日线",
        "market_breadth": "市场宽度",
        "stock_return_distribution": "股票涨跌幅分布",
        "ch_share_fact_market_breadth_daily": "ClickHouse 市场宽度日表",
        "prod_ch_share_fact_market_breadth_daily": "Prod ClickHouse 市场宽度日表",
        "lake_root_health": "Lake 根目录健康",
    }
)


def get_dataset_chinese_name(dataset_id: str) -> str:
    """Return the registered Chinese display name for a stable dataset id."""

    try:
        return DATASET_CHINESE_NAMES[dataset_id]
    except KeyError as error:
        raise KeyError(f"Unknown dataset id for Chinese name mapping: {dataset_id!r}") from error
