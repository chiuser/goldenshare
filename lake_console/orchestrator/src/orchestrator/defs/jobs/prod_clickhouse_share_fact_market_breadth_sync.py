import dagster as dg

from orchestrator.defs.assets.clickhouse_serving import (
    prod_ch_share_fact_market_breadth_daily,
)


prod_clickhouse_share_fact_market_breadth_sync_job = dg.define_asset_job(
    name="prod_clickhouse_share_fact_market_breadth_sync_job",
    selection=(
        dg.AssetSelection.assets(prod_ch_share_fact_market_breadth_daily)
        | dg.AssetSelection.checks_for_assets(prod_ch_share_fact_market_breadth_daily)
    ),
    description="同步本机 ClickHouse 市场宽度日表 serving 副本到 prod ClickHouse。",
)
