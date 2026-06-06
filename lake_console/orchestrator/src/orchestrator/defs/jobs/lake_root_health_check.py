import dagster as dg

from orchestrator.defs.assets.lake_root_health import lake_root_health


lake_root_health_check_job = dg.define_asset_job(
    name="lake_root_health_check_job",
    selection=(
        dg.AssetSelection.assets(lake_root_health)
        | dg.AssetSelection.checks_for_assets(lake_root_health)
    ),
    description="检查 lake root 基础设施健康状态。",
)
