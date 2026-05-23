import dagster as dg

from orchestrator.defs.assets.index_basic import raw_tushare_index_basic, silver_index_basic


index_basic_update_job = dg.define_asset_job(
    name="index_basic_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_index_basic, silver_index_basic)
        | dg.AssetSelection.checks_for_assets(raw_tushare_index_basic, silver_index_basic)
    ),
    description="更新指数基础信息原始表和标准表。",
)
