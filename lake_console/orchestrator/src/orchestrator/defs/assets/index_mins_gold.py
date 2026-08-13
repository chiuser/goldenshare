"""Canonical Gold business-bar assets for ordinary index minutes."""

from pathlib import Path

import dagster as dg

from orchestrator.defs.assets.index_mins_silver_defs import SILVER_INDEX_MINS_ASSETS
from orchestrator.defs.io.cn_a_gold_minute_writer import (
    write_canonical_gold_minute_partition,
)
from orchestrator.defs.partitions import cn_a_index_mins_trade_days
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    gold_index_mins_path,
    gold_index_mins_staging_path,
    lake_path_template,
    silver_index_mins_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import GOLD_INDEX_MINS_SCHEMA
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    CN_A_GOLD_MINUTE_FREQS,
    CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET,
)
from orchestrator.defs.run_contracts.index_mins import INDEX_MINS_GOLD_ASSET_NAMES
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)

_SILVER_BY_FREQ = dict(
    zip(CN_A_GOLD_MINUTE_FREQS, SILVER_INDEX_MINS_ASSETS, strict=True)
)


def _build_asset(*, asset_name: str, target_freq: int) -> dg.AssetsDefinition:
    source_freq = CN_A_GOLD_MINUTE_SOURCE_FREQ_BY_TARGET[target_freq]

    @dg.asset(
        name=asset_name,
        deps=[_SILVER_BY_FREQ[source_freq]],
        partitions_def=cn_a_index_mins_trade_days,
        group_name="index",
        tags=build_asset_tags(layer=AssetLayer.GOLD, data_domain=DataDomain.QUOTE_DATA),
        metadata=build_asset_definition_metadata(
            dataset_id="index_mins",
            source_system=SourceSystem.DERIVED,
            data_contract="canonical_cn_a_index_minute_business_bars",
            column_schema=GOLD_INDEX_MINS_SCHEMA,
            path_template=lake_path_template(
                gold_index_mins_path(
                    PATH_TEMPLATE_LAKE_ROOT,
                    target_freq,
                    PATH_TEMPLATE_PARTITION_KEY,
                )
            ),
            extra_metadata={
                "frequency": target_freq,
                "source_frequency": source_freq,
                "partition_set": cn_a_index_mins_trade_days.name,
                "session_contract": "cn_a_gold_minute_v1",
            },
        ),
        description=f"指数 {target_freq} 分钟 Gold 业务 K 线。",
    )
    def asset(
        context: dg.AssetExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.MaterializeResult:
        lake_root.ensure_available_for_run()
        result = write_canonical_gold_minute_partition(
            duckdb_resource=duckdb,
            source_path=silver_index_mins_path(
                lake_root.root(), f"{source_freq}min", context.partition_key
            ),
            target_path=gold_index_mins_path(
                lake_root.root(), target_freq, context.partition_key
            ),
            staging_path=gold_index_mins_staging_path(
                Path(DEFAULT_LAKE_STAGING_ROOT),
                context.run_id,
                target_freq,
                context.partition_key,
            ),
            target_freq=target_freq,
            partition_key=context.partition_key,
        )
        return dg.MaterializeResult(
            metadata=build_materialization_metadata(
                uri=result.target_path,
                row_count=result.output_row_count,
                observed_columns=tuple(
                    column.name for column in GOLD_INDEX_MINS_SCHEMA
                ),
                extra_metadata=result.to_details(),
            )
        )

    return asset


GOLD_INDEX_MINS_ASSETS = tuple(
    _build_asset(asset_name=asset_name, target_freq=target_freq)
    for asset_name, target_freq in zip(
        INDEX_MINS_GOLD_ASSET_NAMES, CN_A_GOLD_MINUTE_FREQS, strict=True
    )
)

(
    gold_index_mins_1m,
    gold_index_mins_5m,
    gold_index_mins_15m,
    gold_index_mins_30m,
    gold_index_mins_60m,
    gold_index_mins_90m,
    gold_index_mins_120m,
) = GOLD_INDEX_MINS_ASSETS

__all__ = ["GOLD_INDEX_MINS_ASSETS"]
