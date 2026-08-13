"""Independent daily serving job for stock QFQ nine-turn."""

import dagster as dg

from orchestrator.defs.assets.stock_daily_qfq_nineturn_prod_core import (
    prod_core_stock_daily_qfq_nineturn,
)

prod_core_stock_daily_qfq_nineturn_sync_job = dg.define_asset_job(
    name="prod_core_stock_daily_qfq_nineturn_sync_job",
    selection=(
        dg.AssetSelection.assets(prod_core_stock_daily_qfq_nineturn)
        | dg.AssetSelection.checks_for_assets(
            prod_core_stock_daily_qfq_nineturn
        )
    ),
    description=(
        "在自主股票日线前复权九转 Gold 分区及 blocking check 就绪后，"
        "事务发布同一交易日到 prod PostgreSQL serving。"
    ),
)
