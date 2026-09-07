"""External fixed suspension input; publication is a separate manual operation."""

import dagster as dg

from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    lake_path_template,
    silver_stock_suspend_confirmed_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    SILVER_STOCK_SUSPEND_CONFIRMED_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
)
from orchestrator.defs.stock_suspend_confirmed_contract import (
    STOCK_SUSPEND_CONFIRMED_ASSET_KEY,
    STOCK_SUSPEND_CONFIRMED_VERSION,
)

silver_stock_suspend_confirmed = dg.AssetSpec(
    key=STOCK_SUSPEND_CONFIRMED_ASSET_KEY,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="stock_suspend_confirmed", source_system=SourceSystem.SEED,
        data_contract=STOCK_SUSPEND_CONFIRMED_VERSION,
        column_schema=SILVER_STOCK_SUSPEND_CONFIRMED_SCHEMA,
        path_template=lake_path_template(silver_stock_suspend_confirmed_path(PATH_TEMPLATE_LAKE_ROOT)),
    ),
    description="人工批准并一次性发布的历史全日停牌事实；无日期分区、无自动写入或日更要求。仅停牌 Silver 生成链消费。",
)
