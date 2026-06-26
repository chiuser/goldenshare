import dagster as dg

from orchestrator.defs.assets.stock_identity_map import silver_stock_identity_map


stock_identity_map_update_job = dg.define_asset_job(
    name="stock_identity_map_update_job",
    selection=(
        dg.AssetSelection.assets(silver_stock_identity_map)
        | dg.AssetSelection.checks_for_assets(silver_stock_identity_map)
    ),
    description=(
        "在 stock_basic 和 namechange ready 后重建股票身份映射 full snapshot，"
        "并执行 schema、唯一性、seed 引用和枚举域检查。"
    ),
)
