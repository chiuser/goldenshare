import dagster as dg

from orchestrator.defs.assets.stock_basic import raw_tushare_stock_basic, silver_stock_basic
from orchestrator.defs.assets.stock_lifecycle import silver_stock_lifecycle


raw_stock_basic_update_job = dg.define_asset_job(
    name="raw_stock_basic_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_stock_basic)
        | dg.AssetSelection.checks_for_assets(raw_tushare_stock_basic)
    ),
    description=(
        "更新 Tushare 股票基础信息 raw 全状态快照，并执行 raw 字段和主键检查。"
        "失败后先看 raw_tushare_stock_basic 的 check metadata 和 run stdout。"
    ),
)


silver_stock_basic_update_job = dg.define_asset_job(
    name="silver_stock_basic_update_job",
    selection=(
        dg.AssetSelection.assets(silver_stock_basic, silver_stock_lifecycle)
        | dg.AssetSelection.checks_for_assets(
            silver_stock_basic,
            silver_stock_lifecycle,
        )
    ),
    description=(
        "在 raw 股票基础信息 ready 后，同时更新当前上市股票池 silver_stock_basic "
        "和历史生命周期 silver_stock_lifecycle，并执行对应 blocking checks。"
    ),
)
