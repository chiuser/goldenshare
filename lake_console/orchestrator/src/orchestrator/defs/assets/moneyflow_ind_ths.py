"""Independent Raw and Silver THS industry assets, with explicit source identity."""

from pathlib import Path

import dagster as dg

from orchestrator.defs.io.moneyflow_daily_update import (
    update_daily_moneyflow_raw,
    update_daily_moneyflow_silver,
)
from orchestrator.defs.partitions import cn_a_moneyflow_ind_ths_trade_days
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_moneyflow_path,
    silver_moneyflow_path,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_MONEYFLOW_IND_THS_SCHEMA,
    SILVER_MONEYFLOW_IND_THS_SCHEMA,
)
from orchestrator.defs.run_contracts.asset_tags import (
    AssetLayer,
    DataDomain,
    build_asset_tags,
)
from orchestrator.defs.run_contracts.metadata import (
    SourceSystem,
    build_asset_definition_metadata,
    build_materialization_metadata,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_IND_THS_RAW_CHECK,
    MONEYFLOW_WRITER_POOL,
    MoneyflowContractError,
)
from orchestrator.defs.sensors.readiness import (
    AssetReadinessSpec,
    asset_readiness_status,
)


def _result(result: dict, columns) -> dg.MaterializeResult:
    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=result["target"],
            row_count=result["row_count"],
            observed_columns=tuple(c.name for c in columns),
            extra_metadata={
                k: v for k, v in result.items() if k not in {"target", "row_count"}
            },
        )
    )


def _check_cancel(context: dg.AssetExecutionContext) -> None:
    run = context.instance.get_run_by_id(context.run.run_id)
    if run is None or run.status in {
        dg.DagsterRunStatus.CANCELING,
        dg.DagsterRunStatus.CANCELED,
    }:
        raise dg.Failure("moneyflow_run_cancelled")


@dg.asset(
    name="raw_tushare_moneyflow_ind_ths",
    pool=MONEYFLOW_WRITER_POOL,
    partitions_def=cn_a_moneyflow_ind_ths_trade_days,
    group_name="moneyflow",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="moneyflow_ind_ths",
        source_system=SourceSystem.TUSHARE,
        data_contract="tushare_moneyflow_ind_ths_raw_by_trade_date",
        column_schema=RAW_TUSHARE_MONEYFLOW_IND_THS_SCHEMA,
        path_template=lake_path_template(
            raw_moneyflow_path(
                PATH_TEMPLATE_LAKE_ROOT,
                "moneyflow_ind_ths",
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        source_api="moneyflow_ind_ths",
        source_category_path="股票数据/资金流向数据",
        source_doc="docs/sources/tushare/股票数据/资金流向数据/0343_同花顺行业资金流向（THS）.md",
        extra_metadata={
            "partition_set": cn_a_moneyflow_ind_ths_trade_days.name,
            "write_boundary": "verified_candidate_per_file_replace",
        },
    ),
    description="从Tushare完整采集两轮稳定的同花顺行业资金流向，校验候选后逐文件发布Raw。",
)
def raw_tushare_moneyflow_ind_ths(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    try:
        result = update_daily_moneyflow_raw(
            instance=context.instance,
            dataset="moneyflow_ind_ths",
            tushare=tushare,
            lake_root=lake_root.root(),
            staging_root=Path(DEFAULT_LAKE_STAGING_ROOT),
            operation_id=context.run.run_id,
            trade_date=context.partition_key,
            check_cancel=lambda: _check_cancel(context),
        )
    except MoneyflowContractError as error:
        raise dg.Failure(
            "同花顺行业资金流采集或发布未完成。",
            metadata={
                "goldenshare/reason_code": str(error),
                "goldenshare/retryable": error.retryable,
            },
        ) from error
    return _result(result, RAW_TUSHARE_MONEYFLOW_IND_THS_SCHEMA)


@dg.asset(
    name="silver_moneyflow_ind_ths",
    pool=MONEYFLOW_WRITER_POOL,
    deps=[raw_tushare_moneyflow_ind_ths],
    partitions_def=cn_a_moneyflow_ind_ths_trade_days,
    group_name="moneyflow",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="moneyflow_ind_ths",
        source_system=SourceSystem.DERIVED,
        data_contract="standardized_moneyflow_ind_ths_by_trade_date",
        column_schema=SILVER_MONEYFLOW_IND_THS_SCHEMA,
        path_template=lake_path_template(
            silver_moneyflow_path(
                PATH_TEMPLATE_LAKE_ROOT,
                "moneyflow_ind_ths",
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        extra_metadata={
            "partition_set": cn_a_moneyflow_ind_ths_trade_days.name,
            "write_boundary": "verified_candidate_per_file_replace",
        },
    ),
    description="只读同日已绿Raw，将同花顺行业资金流trade_date标准化为DATE，其余字段保真。",
)
def silver_moneyflow_ind_ths(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    # DuckDB resource is part of the declared execution surface; the writer uses
    # the existing moneyflow-specific configured connection (512MB/one thread).
    lake_root.ensure_available_for_run()
    key = raw_tushare_moneyflow_ind_ths.key
    status = asset_readiness_status(
        context.instance,
        AssetReadinessSpec(key, (MONEYFLOW_IND_THS_RAW_CHECK,)),
        partition_key=context.partition_key,
    )
    if not status.ready:
        raise dg.Failure(f"moneyflow_raw_not_ready:{status.reason}")
    records = context.instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=key, asset_partitions=[context.partition_key]),
        limit=1,
    ).records
    if not records or records[0].storage_id != status.materialization_storage_id:
        raise dg.Failure("moneyflow_raw_materialization_changed")
    metadata = records[0].asset_materialization.metadata
    hash_metadata = metadata.get("goldenshare/file_sha256")
    expected_hash = hash_metadata.value if hash_metadata is not None else None
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise dg.Failure("moneyflow_raw_hash_missing")
    result = update_daily_moneyflow_silver(
        dataset="moneyflow_ind_ths",
        lake_root=lake_root.root(),
        staging_root=Path(DEFAULT_LAKE_STAGING_ROOT),
        operation_id=context.run.run_id,
        trade_date=context.partition_key,
        expected_raw_hash=expected_hash,
        check_cancel=lambda: _check_cancel(context),
    )
    return _result(result, SILVER_MONEYFLOW_IND_THS_SCHEMA)
