import dagster as dg

from orchestrator.defs.assets.adj_factor import raw_tushare_adj_factor, silver_adj_factor


raw_adj_factor_update_job = dg.define_asset_job(
    name="raw_adj_factor_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_adj_factor)
        | dg.AssetSelection.checks_for_assets(raw_tushare_adj_factor)
    ),
    description="更新股票复权因子 raw 源站镜像。",
)


silver_adj_factor_update_job = dg.define_asset_job(
    name="silver_adj_factor_update_job",
    selection=(
        dg.AssetSelection.assets(silver_adj_factor)
        | dg.AssetSelection.checks_for_assets(silver_adj_factor)
    ),
    description="raw 复权因子和股票基础信息 ready 后，更新股票复权因子 silver 标准表。",
)
