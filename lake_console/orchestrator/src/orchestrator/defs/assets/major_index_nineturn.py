"""Major-index daily and minute nine-turn Gold assets."""

from pathlib import Path
from time import perf_counter

import dagster as dg

from orchestrator.defs.assets.major_index_mins_gold import (
    GOLD_MAJOR_INDEX_MINS_ASSETS,
)
from orchestrator.defs.assets.market_major_indices import (
    gold_market_major_indices_daily,
)
from orchestrator.defs.major_index_nineturn import (
    build_gold_major_index_daily_nineturn_partition_select_sql,
    build_gold_major_index_mins_nineturn_partition_select_sql,
    plan_gold_major_index_daily_nineturn_source,
    plan_gold_major_index_mins_nineturn_source,
    write_gold_major_index_daily_nineturn_partition,
    write_gold_major_index_mins_nineturn_partition,
)
from orchestrator.defs.partitions import (
    cn_a_index_trade_days,
    cn_major_index_mins_trade_days,
)
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    gold_major_index_daily_nineturn_path,
    gold_major_index_mins_nineturn_path,
    lake_path_template,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_MAJOR_INDEX_DAILY_NINETURN_SCHEMA,
    GOLD_MAJOR_INDEX_MINS_NINETURN_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.major_index_nineturn import (
    MAJOR_INDEX_NINETURN_COMPARISON_LAG,
    MAJOR_INDEX_NINETURN_DAILY_ASSET_KEY,
    MAJOR_INDEX_NINETURN_MINUTE_ASSET_KEYS,
    MAJOR_INDEX_NINETURN_MINUTE_FREQS,
    MAJOR_INDEX_NINETURN_SIGNAL_THRESHOLD,
    MAJOR_INDEX_NINETURN_VERSION,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.utils.dg_log_helper import DgStdoutLogger


def _previous_registered_trade_date(
    context: dg.AssetExecutionContext,
    *,
    partition_set_name: str,
) -> str | None:
    earlier = sorted(
        key
        for key in context.instance.get_dynamic_partitions(partition_set_name)
        if key < context.partition_key
    )
    return earlier[-1] if earlier else None


def _materialization_metadata(result, *, partition_key: str, freq: int | None):
    label = "日线" if freq is None else f"{freq} 分钟"
    return build_materialization_metadata(
        uri=result.target_path,
        row_count=result.output_row_count,
        observed_columns=result.observed_columns,
        extra_metadata={
            "summary": f"已生成主要指数{label}九转分区。",
            "next_action": "等待同分区 blocking integrity check 通过。",
            "result_status": "written",
            "partition_key": partition_key,
            "freq": freq if freq is not None else "daily",
            "source_file_count": result.source_file_count,
            "source_row_count": result.source_row_count,
            "output_row_count": result.output_row_count,
            "index_code_count": result.index_code_count,
            "source_fingerprint": result.source_fingerprint,
            "formula_version": MAJOR_INDEX_NINETURN_VERSION,
        },
    )


@dg.asset(
    name=MAJOR_INDEX_NINETURN_DAILY_ASSET_KEY,
    deps=[
        dg.AssetDep(
            gold_market_major_indices_daily,
            partition_mapping=dg.IdentityPartitionMapping(),
        )
    ],
    partitions_def=cn_a_index_trade_days,
    group_name="index",
    tags=build_asset_tags(layer=AssetLayer.GOLD, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id="major_index_daily_nineturn",
        source_system=SourceSystem.DERIVED,
        data_contract="major_index_daily_nineturn",
        column_schema=GOLD_MAJOR_INDEX_DAILY_NINETURN_SCHEMA,
        path_template=lake_path_template(
            gold_major_index_daily_nineturn_path(
                PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY
            )
        ),
        extra_metadata={
            "source_asset": "gold_market_major_indices_daily",
            "formula_version": MAJOR_INDEX_NINETURN_VERSION,
            "comparison_lag": MAJOR_INDEX_NINETURN_COMPARISON_LAG,
            "signal_threshold": MAJOR_INDEX_NINETURN_SIGNAL_THRESHOLD,
            "physical_universe": "major_indices_cn_a_11_code_seed",
            "calculation_model": "fixed_formula_non_repainting",
        },
    ),
    description="主要指数日线九转，按 11-code 物理 seed 使用不复权 close 计算。",
)
def gold_major_index_daily_nineturn(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    started = perf_counter()
    previous_trade_date = _previous_registered_trade_date(
        context, partition_set_name=cn_a_index_trade_days.name
    )
    with duckdb.connect() as connection:
        plan = plan_gold_major_index_daily_nineturn_source(
            connection,
            lake_root=lake_root.root(),
            partition_key=context.partition_key,
            previous_trade_date=previous_trade_date,
        )
    select_sql = build_gold_major_index_daily_nineturn_partition_select_sql(
        source_paths=plan.source_paths,
        target_trade_date=context.partition_key,
        previous_partition_path=plan.previous_partition_path,
    )
    result = write_gold_major_index_daily_nineturn_partition(
        duckdb_resource=duckdb,
        lake_root=lake_root.root(),
        staging_root=Path(DEFAULT_LAKE_STAGING_ROOT),
        partition_key=context.partition_key,
        run_id=context.run_id,
        select_sql=select_sql,
        source_paths=plan.source_paths,
        previous_partition_path=plan.previous_partition_path,
        source_row_count=plan.source_row_count,
    )
    DgStdoutLogger("major_index_nineturn").stdout(
        "major_index_nineturn_completed",
        asset=MAJOR_INDEX_NINETURN_DAILY_ASSET_KEY,
        partition_key=context.partition_key,
        freq="daily",
        output_row_count=result.output_row_count,
        elapsed_ms=round((perf_counter() - started) * 1000, 3),
    )
    return dg.MaterializeResult(
        metadata=_materialization_metadata(
            result, partition_key=context.partition_key, freq=None
        )
    )


_GOLD_MINUTE_SOURCE_BY_FREQ = dict(
    zip((1, 5, 15, 30, 60, 90, 120), GOLD_MAJOR_INDEX_MINS_ASSETS, strict=True)
)


def _build_minute_asset(*, asset_name: str, freq: int) -> dg.AssetsDefinition:
    source_asset = _GOLD_MINUTE_SOURCE_BY_FREQ[freq]

    @dg.asset(
        name=asset_name,
        deps=[
            dg.AssetDep(source_asset, partition_mapping=dg.IdentityPartitionMapping())
        ],
        partitions_def=cn_major_index_mins_trade_days,
        group_name="index",
        tags=build_asset_tags(
            layer=AssetLayer.GOLD, data_domain=DataDomain.INDEX_TOPIC
        ),
        metadata=build_asset_definition_metadata(
            dataset_id="major_index_mins_nineturn",
            source_system=SourceSystem.DERIVED,
            data_contract="major_index_minute_nineturn",
            column_schema=GOLD_MAJOR_INDEX_MINS_NINETURN_SCHEMA,
            path_template=lake_path_template(
                gold_major_index_mins_nineturn_path(
                    PATH_TEMPLATE_LAKE_ROOT, freq, PATH_TEMPLATE_PARTITION_KEY
                )
            ),
            extra_metadata={
                "source_asset": f"gold_major_index_mins_{freq}m",
                "freq": freq,
                "formula_version": MAJOR_INDEX_NINETURN_VERSION,
                "comparison_lag": MAJOR_INDEX_NINETURN_COMPARISON_LAG,
                "signal_threshold": MAJOR_INDEX_NINETURN_SIGNAL_THRESHOLD,
                "calculation_model": "fixed_formula_non_repainting",
                "physical_universe": "major_index_mins_gold_without_899050_bj",
            },
        ),
        description=f"主要指数 {freq} 分钟九转，只消费同频规范化 Gold K 线。",
    )
    def asset(
        context: dg.AssetExecutionContext,
        lake_root: LakeRootResource,
        duckdb: DuckDBResource,
    ) -> dg.MaterializeResult:
        lake_root.ensure_available_for_run()
        started = perf_counter()
        previous_trade_date = _previous_registered_trade_date(
            context, partition_set_name=cn_major_index_mins_trade_days.name
        )
        with duckdb.connect() as connection:
            plan = plan_gold_major_index_mins_nineturn_source(
                connection,
                lake_root=lake_root.root(),
                freq=freq,
                partition_key=context.partition_key,
                previous_trade_date=previous_trade_date,
            )
        select_sql = build_gold_major_index_mins_nineturn_partition_select_sql(
            source_paths=plan.source_paths,
            freq=freq,
            target_trade_date=context.partition_key,
            previous_partition_path=plan.previous_partition_path,
        )
        result = write_gold_major_index_mins_nineturn_partition(
            duckdb_resource=duckdb,
            lake_root=lake_root.root(),
            staging_root=Path(DEFAULT_LAKE_STAGING_ROOT),
            freq=freq,
            partition_key=context.partition_key,
            run_id=context.run_id,
            select_sql=select_sql,
            source_paths=plan.source_paths,
            previous_partition_path=plan.previous_partition_path,
            source_row_count=plan.source_row_count,
        )
        DgStdoutLogger("major_index_nineturn").stdout(
            "major_index_nineturn_completed",
            asset=asset_name,
            partition_key=context.partition_key,
            freq=freq,
            output_row_count=result.output_row_count,
            elapsed_ms=round((perf_counter() - started) * 1000, 3),
        )
        return dg.MaterializeResult(
            metadata=_materialization_metadata(
                result, partition_key=context.partition_key, freq=freq
            )
        )

    return asset


GOLD_MAJOR_INDEX_MINS_NINETURN_ASSETS = tuple(
    _build_minute_asset(asset_name=asset_name, freq=freq)
    for asset_name, freq in zip(
        MAJOR_INDEX_NINETURN_MINUTE_ASSET_KEYS,
        MAJOR_INDEX_NINETURN_MINUTE_FREQS,
        strict=True,
    )
)

(
    gold_major_index_mins_nineturn_5m,
    gold_major_index_mins_nineturn_15m,
    gold_major_index_mins_nineturn_30m,
    gold_major_index_mins_nineturn_60m,
    gold_major_index_mins_nineturn_90m,
    gold_major_index_mins_nineturn_120m,
) = GOLD_MAJOR_INDEX_MINS_NINETURN_ASSETS

GOLD_MAJOR_INDEX_NINETURN_ASSETS = (
    gold_major_index_daily_nineturn,
    *GOLD_MAJOR_INDEX_MINS_NINETURN_ASSETS,
)


__all__ = [
    "GOLD_MAJOR_INDEX_MINS_NINETURN_ASSETS",
    "GOLD_MAJOR_INDEX_NINETURN_ASSETS",
    "gold_major_index_daily_nineturn",
]
