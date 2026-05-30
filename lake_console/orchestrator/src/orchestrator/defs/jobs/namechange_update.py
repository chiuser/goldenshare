import dagster as dg

from orchestrator.defs.assets.namechange import raw_tushare_namechange, silver_namechange


namechange_update_job = dg.define_asset_job(
    name="namechange_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_namechange, silver_namechange)
        | dg.AssetSelection.checks_for_assets(raw_tushare_namechange, silver_namechange)
    ),
    description="更新股票曾用名原始表和标准表。",
)
