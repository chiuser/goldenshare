import dagster as dg

from orchestrator.defs.assets.namechange import raw_tushare_namechange, silver_namechange


raw_namechange_update_job = dg.define_asset_job(
    name="raw_namechange_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_namechange)
        | dg.AssetSelection.checks_for_assets(raw_tushare_namechange)
    ),
    description="更新股票曾用名 raw full snapshot。",
)


silver_namechange_update_job = dg.define_asset_job(
    name="silver_namechange_update_job",
    selection=(
        dg.AssetSelection.assets(silver_namechange)
        | dg.AssetSelection.checks_for_assets(silver_namechange)
    ),
    description="raw 股票曾用名和 stock_basic ready 后，更新股票曾用名 silver full snapshot。",
)
