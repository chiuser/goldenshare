"""Single-day Gold output from a continuous r4.1 replay."""

from collections.abc import Iterator
from datetime import date

import dagster as dg

from orchestrator.defs.io.major_index_quantitative_structure import (
    StructureDay,
    StructureInputError,
    calculate_structure_days,
    structure_algorithm_version,
    structure_materialization_metadata,
    structure_trade_dates,
    structure_writer_lock,
    write_structure_day,
)
from orchestrator.defs.partitions import (
    cn_major_index_quantitative_structure_trade_days,
)
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    gold_major_index_quantitative_structure_path,
    gold_major_index_quantitative_structure_staging_dir,
    lake_path_template,
    quantitative_structure_staging_root,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_MAJOR_INDEX_QUANTITATIVE_STRUCTURE_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_SILVER_ASSET_KEY,
    IDX_FACTOR_PRO_SILVER_CHECKS,
)
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_GOLD_ASSET_KEYS,
    MAJOR_INDEX_MINS_GOLD_CHECKS,
)
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    major_index_mins_technical_asset_key,
    major_index_mins_technical_checks,
)
from orchestrator.defs.run_contracts.major_index_quantitative_structure import (
    STRUCTURE_ASSET,
    STRUCTURE_CONTRACT,
    STRUCTURE_DATASET,
    STRUCTURE_FREQUENCIES,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
)
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    partition_dataset_readiness_status_from_latest_checks,
)

STRUCTURE_UPSTREAM_SPECS = (
    AssetReadinessSpec(dg.AssetKey(IDX_FACTOR_PRO_SILVER_ASSET_KEY), IDX_FACTOR_PRO_SILVER_CHECKS),
    *(
        AssetReadinessSpec(dg.AssetKey(asset_key), (check,))
        for asset_key, check in zip(MAJOR_INDEX_MINS_GOLD_ASSET_KEYS, MAJOR_INDEX_MINS_GOLD_CHECKS)
        if asset_key in {f"gold_major_index_mins_{freq}m" for freq in STRUCTURE_FREQUENCIES}
    ),
    *(
        AssetReadinessSpec(
            dg.AssetKey(major_index_mins_technical_asset_key(freq)),
            major_index_mins_technical_checks(freq),
        )
        for freq in STRUCTURE_FREQUENCIES
    ),
)


@dg.asset(
    name=STRUCTURE_ASSET,
    group_name="index",
    partitions_def=cn_major_index_quantitative_structure_trade_days,
    deps=[
        "silver_trade_calendar",
        *(
            dg.AssetDep(spec.asset_key, partition_mapping=dg.IdentityPartitionMapping())
            for spec in STRUCTURE_UPSTREAM_SPECS
        ),
    ],
    tags=build_asset_tags(layer=AssetLayer.GOLD, data_domain=DataDomain.INDEX_TOPIC),
    metadata=build_asset_definition_metadata(
        dataset_id=STRUCTURE_DATASET,
        source_system=SourceSystem.DERIVED,
        data_contract=STRUCTURE_CONTRACT,
        column_schema=GOLD_MAJOR_INDEX_QUANTITATIVE_STRUCTURE_SCHEMA,
        path_template=lake_path_template(gold_major_index_quantitative_structure_path(
            PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY,
        )),
    ),
    output_required=False,
    description="按交易日保存主要指数的量化结构事件，供财势乾坤读取。",
)
def gold_major_index_quantitative_structure(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> Iterator[dg.MaterializeResult]:
    partition_key = context.partition_key
    upstream = partition_dataset_readiness_status_from_latest_checks(
        context.instance, STRUCTURE_UPSTREAM_SPECS, partition_key=partition_key,
    )
    if not upstream.ready:
        context.log.info(f"{partition_key} 等待上游就绪：{upstream.reason}")
        return
    lake_root.ensure_available_for_run()
    target_day = date.fromisoformat(partition_key)
    root = lake_root.root()
    staging_root = quantitative_structure_staging_root(root)
    staging_dir = gold_major_index_quantitative_structure_staging_dir(staging_root, context.run.run_id)
    target = gold_major_index_quantitative_structure_path(root, partition_key)
    algorithm_version = structure_algorithm_version()

    def log_month(through: date, input_count: int, elapsed: float) -> None:
        context.log.info(f"计算至 {through}，累计 {input_count} 根，本批 {elapsed:.2f} 秒")

    with structure_writer_lock(staging_root), duckdb.connect() as connection:
        days = structure_trade_dates(connection, root, target_day)
        if not days or days[-1] != target_day:
            raise ValueError(f"{partition_key} 不在量化结构的 SSE 开市日范围")
        try:
            structure_day, = calculate_structure_days(
                connection, root, days, first_result_date=target_day, report_month=log_month,
            )
        except StructureInputError as exc:
            context.log.error(str(exc))
            input_count = exc.input_bar_count if exc.trade_date == target_day else 0
            structure_day = StructureDay(target_day, False, [], input_count)
        write_structure_day(connection, structure_day, staging_dir=staging_dir, target=target)
        yield dg.MaterializeResult(metadata=structure_materialization_metadata(
            target,
            algorithm_version=algorithm_version,
            input_bar_count=structure_day.input_bar_count,
            event_count=len(structure_day.results),
        ))
