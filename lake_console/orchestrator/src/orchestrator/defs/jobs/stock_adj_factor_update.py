import dagster as dg

from orchestrator.defs.assets.adj_factor import raw_tushare_adj_factor, silver_adj_factor


stock_adj_factor_update_job = dg.define_asset_job(
    name="stock_adj_factor_update_job",
    selection=(
        dg.AssetSelection.assets(raw_tushare_adj_factor, silver_adj_factor)
        | dg.AssetSelection.checks_for_assets(raw_tushare_adj_factor, silver_adj_factor)
    ),
    description="更新股票复权因子原始表和标准表，股票基础信息作为只读前置事实。",
)
