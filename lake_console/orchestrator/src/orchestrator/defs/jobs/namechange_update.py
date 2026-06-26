import dagster as dg

from orchestrator.defs.assets.namechange import raw_tushare_namechange, silver_namechange


raw_namechange_update_job = dg.define_asset_job(
    name="raw_namechange_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_namechange)
        | dg.AssetSelection.checks_for_assets(raw_tushare_namechange)
    ),
    description=(
        "更新股票曾用名 raw 去重全量快照，并执行字段、日期和重复行检查。"
        "失败后先看 raw_namechange checks 和 run stdout。"
    ),
)


silver_namechange_update_job = dg.define_asset_job(
    name="silver_namechange_update_job",
    selection=(
        dg.AssetSelection.assets(silver_namechange)
        | dg.AssetSelection.checks_for_assets(silver_namechange)
    ),
    description=(
        "在 raw 股票曾用名和 stock_basic ready 后，生成股票曾用名 silver 时间线，"
        "并执行区间唯一性和重叠检查。"
    ),
)
