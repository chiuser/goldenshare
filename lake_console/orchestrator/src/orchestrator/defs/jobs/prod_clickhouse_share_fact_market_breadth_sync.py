import dagster as dg

from orchestrator.defs.assets.clickhouse_serving import (
    prod_ch_share_fact_market_breadth_daily,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days


def _empty_check_refresh_run_config(_partition_key: str) -> dict[str, object]:
    return {}


prod_clickhouse_share_fact_market_breadth_sync_job = dg.define_asset_job(
    name="prod_clickhouse_share_fact_market_breadth_sync_job",
    selection=(
        dg.AssetSelection.assets(prod_ch_share_fact_market_breadth_daily)
        | dg.AssetSelection.checks_for_assets(prod_ch_share_fact_market_breadth_daily)
    ),
    description="同步本机 ClickHouse 市场宽度日表 serving 副本到 prod ClickHouse。",
)


prod_clickhouse_share_fact_market_breadth_check_refresh_job = dg.define_asset_job(
    name="prod_clickhouse_share_fact_market_breadth_check_refresh_job",
    selection=dg.AssetSelection.checks_for_assets(
        prod_ch_share_fact_market_breadth_daily
    ),
    config=dg.PartitionedConfig(
        partitions_def=cn_a_stock_trade_days,
        run_config_for_partition_key_fn=_empty_check_refresh_run_config,
    ),
    partitions_def=cn_a_stock_trade_days,
    description=(
        "仅刷新 prod ClickHouse 市场宽度日表的 asset checks；"
        "不 materialize 资产，不改写 ClickHouse 数据。"
    ),
)
