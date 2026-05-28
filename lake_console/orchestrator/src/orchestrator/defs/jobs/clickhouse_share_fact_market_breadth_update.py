import dagster as dg

from orchestrator.defs.assets.clickhouse_serving import (
    ch_share_fact_market_breadth_daily,
)


clickhouse_share_fact_market_breadth_update_job = dg.define_asset_job(
    name="clickhouse_share_fact_market_breadth_update_job",
    selection=(
        dg.AssetSelection.assets(ch_share_fact_market_breadth_daily)
        | dg.AssetSelection.checks_for_assets(ch_share_fact_market_breadth_daily)
    ),
    description="更新 ClickHouse 行情事实市场宽度日表 serving 副本。",
)
