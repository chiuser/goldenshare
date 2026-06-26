import dagster as dg

from orchestrator.defs.assets.index_basic import raw_tushare_index_basic, silver_index_basic


index_basic_update_job = dg.define_asset_job(
    name="index_basic_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_index_basic, silver_index_basic)
        | dg.AssetSelection.checks_for_assets(raw_tushare_index_basic, silver_index_basic)
    ),
    description=(
        "更新 Tushare 指数基础信息 raw 和有效指数池 silver，并执行字段、主键、"
        "日期和终止指数过滤检查。失败后先看 index_basic checks。"
    ),
)
