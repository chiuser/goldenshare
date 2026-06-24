from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from datetime import datetime
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.assets.market_breadth import gold_market_breadth_daily
from orchestrator.defs.assets.stock_daily import (
    raw_tushare_stock_daily,
    silver_stock_daily,
)
from orchestrator.defs.assets.stock_return_distribution import (
    gold_stock_return_distribution,
)
from orchestrator.defs.assets.suspend_d import (
    raw_tushare_suspend_d,
    silver_stock_suspend_daily,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days


CN_A_TIMEZONE = ZoneInfo("Asia/Shanghai")
STOCK_TRADE_DAY_MIN_DATE = "2014-01-01"


def _stock_partition_key_allowed_result(
    context: dg.AssetCheckExecutionContext,
) -> dg.AssetCheckResult:
    partition_key = context.partition_key
    today = datetime.now(CN_A_TIMEZONE).date().isoformat()
    registered_keys = set(
        context.instance.get_dynamic_partitions(cn_a_stock_trade_days.name)
    )

    is_registered = partition_key in registered_keys
    is_not_before_start = partition_key >= STOCK_TRADE_DAY_MIN_DATE
    is_not_future = partition_key <= today

    return dg.AssetCheckResult(
        passed=is_registered and is_not_before_start and is_not_future,
        metadata=build_check_metadata(
            check_scope=CheckScope.PARTITION_ALIGNMENT,
            extra_metadata={
                "partition_key": partition_key,
                "partition_set": cn_a_stock_trade_days.name,
                "is_registered": is_registered,
                "min_trade_date": STOCK_TRADE_DAY_MIN_DATE,
                "is_not_before_start": is_not_before_start,
                "today": today,
                "is_not_future": is_not_future,
            },
        ),
    )


@dg.asset_check(asset=raw_tushare_suspend_d, blocking=True)
def raw_suspend_d_stock_partition_key_allowed(
    context: dg.AssetCheckExecutionContext,
) -> dg.AssetCheckResult:
    return _stock_partition_key_allowed_result(context)


@dg.asset_check(asset=silver_stock_suspend_daily, blocking=True)
def silver_suspend_d_stock_partition_key_allowed(
    context: dg.AssetCheckExecutionContext,
) -> dg.AssetCheckResult:
    return _stock_partition_key_allowed_result(context)


def raw_stock_daily_stock_partition_key_allowed(
    context: dg.AssetCheckExecutionContext,
) -> dg.AssetCheckResult:
    return _stock_partition_key_allowed_result(context)


def silver_stock_daily_stock_partition_key_allowed(
    context: dg.AssetCheckExecutionContext,
) -> dg.AssetCheckResult:
    return _stock_partition_key_allowed_result(context)


@dg.asset_check(asset=raw_tushare_stock_daily, blocking=True)
def raw_stock_daily_partition_allowed_check(
    context: dg.AssetCheckExecutionContext,
) -> dg.AssetCheckResult:
    return raw_stock_daily_stock_partition_key_allowed(context)


@dg.asset_check(asset=silver_stock_daily, blocking=True)
def silver_stock_daily_partition_allowed_check(
    context: dg.AssetCheckExecutionContext,
) -> dg.AssetCheckResult:
    return silver_stock_daily_stock_partition_key_allowed(context)


@dg.asset_check(asset=gold_market_breadth_daily, blocking=True)
def gold_market_breadth_stock_partition_key_allowed(
    context: dg.AssetCheckExecutionContext,
) -> dg.AssetCheckResult:
    return _stock_partition_key_allowed_result(context)


@dg.asset_check(asset=gold_stock_return_distribution, blocking=True)
def gold_stock_return_distribution_stock_partition_key_allowed(
    context: dg.AssetCheckExecutionContext,
) -> dg.AssetCheckResult:
    return _stock_partition_key_allowed_result(context)
