from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.stock_lifecycle import silver_stock_lifecycle
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import (
    ADJ_FACTOR_RAW_REQUIRED_COLUMNS,
    adj_factor_normalized_select,
    adj_factor_retained_record_predicate_sql,
    adj_factor_retained_stock_select,
    count_parquet_query,
    describe_parquet_query,
    silver_cny_stock_lifecycle_select,
)
from orchestrator.defs.io.adj_factor_silver_candidate import (
    build_silver_adj_factor_candidate,
    normalize_restore_keys,
)
from orchestrator.defs.io.adj_factor_silver_publication import publish_silver_adj_factor
from orchestrator.defs.partitions import cn_a_stock_current_trade_days
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    lake_path_template,
    raw_adj_factor_path,
    silver_adj_factor_path,
    silver_stock_lifecycle_path,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_ADJ_FACTOR_SCHEMA,
    SILVER_ADJ_FACTOR_SCHEMA,
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
from orchestrator.defs.tushare_api_io import fetch_tushare_partition_to_raw
from orchestrator.utils.dg_log_helper import DgStdoutLogger

ADJ_FACTOR_COLUMNS = tuple(column.name for column in SILVER_ADJ_FACTOR_SCHEMA)

ADJ_FACTOR_RAW_COLUMN_TYPES = {
    column.name: column.type for column in RAW_TUSHARE_ADJ_FACTOR_SCHEMA
}

ADJ_FACTOR_SILVER_COLUMN_TYPES = {
    column.name: column.type for column in SILVER_ADJ_FACTOR_SCHEMA
}


@dataclass(frozen=True)
class SilverAdjFactorPartitionWriteResult:
    raw_file_path: Path
    stock_lifecycle_file_path: Path
    silver_file_path: Path
    source_row_count: int
    lifecycle_stock_count: int
    selected_row_count: int
    rejected_row_count: int
    row_count: int
    observed_columns: tuple[str, ...]
    restored_row_count: int = 0
    unchanged: bool = False
    source_eligible_row_count: int = 0
    preserved_row_count: int = 0
    write_mode: str = "normal"

    def materialization_extra_metadata(self, partition_key: str) -> dict[str, object]:
        return {
            "raw_file_path": str(self.raw_file_path),
            "stock_lifecycle_file_path": str(self.stock_lifecycle_file_path),
            "partition_key": partition_key,
            "source_row_count": self.source_row_count,
            "lifecycle_stock_count": self.lifecycle_stock_count,
            "selected_row_count": self.selected_row_count,
            "rejected_row_count": self.rejected_row_count,
            "restored_row_count": self.restored_row_count,
            "unchanged": self.unchanged,
            "source_eligible_row_count": self.source_eligible_row_count,
            "preserved_row_count": self.preserved_row_count,
            "write_mode": self.write_mode,
        }


def _column_names(
    connection, path: Path, *, hive_partitioning: bool = False
) -> list[str]:
    rows = connection.execute(
        describe_parquet_query(path, hive_partitioning=hive_partitioning)
    ).fetchall()
    return [row[0] for row in rows]


def _row_count(connection, path: Path, *, hive_partitioning: bool = False) -> int:
    return int(
        connection.execute(
            count_parquet_query(path, hive_partitioning=hive_partitioning)
        ).fetchone()[0]
    )


def _human_materialization_metadata(
    *,
    summary: str,
    next_action: str,
    result_status: str,
    input_summary: dict[str, Any] | None = None,
    filter_summary: dict[str, Any] | None = None,
    diagnostic_ref: str,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "goldenshare/summary": summary,
        "goldenshare/next_action": next_action,
        "goldenshare/result_status": result_status,
        "goldenshare/diagnostic_ref": diagnostic_ref,
    }
    if input_summary:
        metadata["goldenshare/input_summary"] = input_summary
    if filter_summary:
        metadata["goldenshare/filter_summary"] = filter_summary
    return metadata


def _silver_filter_counts(
    connection,
    raw_path: Path,
    stock_lifecycle_path: Path,
) -> dict[str, int]:
    normalized_sql = adj_factor_normalized_select(raw_path)
    row = connection.execute(
        f"""
        WITH normalized AS (
          {normalized_sql}
        ),
        stock_lifecycle AS (
          {adj_factor_retained_stock_select(stock_lifecycle_path)}
        ),
        selected AS (
          SELECT normalized.*
          FROM normalized
          INNER JOIN stock_lifecycle USING (ts_code)
          WHERE {adj_factor_retained_record_predicate_sql('normalized.trade_date', lifecycle_alias='stock_lifecycle')}
        )
        SELECT
          (SELECT count(*) FROM normalized) AS source_row_count,
          (SELECT count(*) FROM ({silver_cny_stock_lifecycle_select(stock_lifecycle_path)})) AS lifecycle_stock_count,
          (SELECT count(*) FROM selected) AS selected_row_count,
          (SELECT count(*) FROM normalized) - (SELECT count(*) FROM selected)
            AS rejected_row_count
        """
    ).fetchone()
    return {
        "source_row_count": int(row[0]),
        "lifecycle_stock_count": int(row[1]),
        "selected_row_count": int(row[2]),
        "rejected_row_count": int(row[3]),
    }


def write_silver_adj_factor_partition(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    partition_key: str,
    publication_id: str,
    overwrite: bool = False,
    staging_root: Path = Path(DEFAULT_LAKE_STAGING_ROOT),
    restore_missing_keys: Sequence[Mapping[str, str]] = (),
) -> SilverAdjFactorPartitionWriteResult:
    restore_keys = normalize_restore_keys(restore_missing_keys, partition_key)
    raw_path = raw_adj_factor_path(lake_root, partition_key)
    stock_lifecycle_path = silver_stock_lifecycle_path(lake_root)
    target_path = silver_adj_factor_path(lake_root, partition_key)
    with connect_configured_duckdb() as connection:
        def build_candidate(candidate: Path) -> dict:
            return build_silver_adj_factor_candidate(
                connection, candidate=candidate, target=target_path,
                raw_path=raw_path, lifecycle=stock_lifecycle_path, day=partition_key,
                restore_keys=restore_keys, overwrite=overwrite,
                filter_counts=_silver_filter_counts(connection, raw_path, stock_lifecycle_path),
            )

        result = publish_silver_adj_factor(
            lake_root=lake_root, staging_root=staging_root, publication_id=publication_id,
            trade_date=partition_key, target=target_path,
            sources=(raw_path, stock_lifecycle_path), restore_keys=restore_keys,
            build_candidate=build_candidate,
        )
        columns = tuple(
            _column_names(connection, target_path, hive_partitioning=False)
        )

    return SilverAdjFactorPartitionWriteResult(
        raw_file_path=raw_path,
        stock_lifecycle_file_path=stock_lifecycle_path,
        silver_file_path=target_path,
        source_row_count=result["source_row_count"],
        lifecycle_stock_count=result["lifecycle_stock_count"],
        selected_row_count=result["selected_row_count"],
        rejected_row_count=result["rejected_row_count"],
        row_count=result["rows"],
        observed_columns=columns,
        restored_row_count=result["restored_row_count"],
        unchanged=result["unchanged"],
        source_eligible_row_count=result["source_eligible_row_count"],
        preserved_row_count=result["preserved_row_count"],
        write_mode=result["write_mode"],
    )


@dg.asset(
    name="raw_tushare_adj_factor",
    partitions_def=cn_a_stock_current_trade_days,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.RAW, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="adj_factor",
        source_system=SourceSystem.TUSHARE,
        source_api="adj_factor",
        source_category_path="股票数据 / 行情数据",
        source_doc="docs/sources/tushare/股票数据/行情数据/0028_复权因子.md",
        data_contract="source_mirror",
        column_schema=RAW_TUSHARE_ADJ_FACTOR_SCHEMA,
        path_template=lake_path_template(
            raw_adj_factor_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)
        ),
        extra_metadata={
            "raw_contract": (
                "Tushare adj_factor source mirror: trade_date is a YYYYMMDD string."
            ),
            "write_summary": (
                "Tushare API rows are written to raw parquet with explicit source "
                "contract fields."
            ),
        },
    ),
    description="Tushare 复权因子 raw 源镜像，按股票当前交易日保存后续 qfq 计算所需复权因子。",
)
def raw_tushare_adj_factor(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    tushare: TushareResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    target_path = raw_adj_factor_path(lake_root.root(), partition_key)
    log = DgStdoutLogger("adj_factor")
    log.stdout(
        "raw_adj_factor_started",
        partition_key=partition_key,
        allow_empty=False,
    )
    metadata = fetch_tushare_partition_to_raw(
        tushare=tushare,
        duckdb=duckdb,
        api_name="adj_factor",
        api_params={"trade_date": partition_key.replace("-", "")},
        fields=ADJ_FACTOR_RAW_REQUIRED_COLUMNS,
        column_types=ADJ_FACTOR_RAW_COLUMN_TYPES,
        target_path=target_path,
        partition_key=partition_key,
        allow_empty=False,
    )
    metadata.update(
        _human_materialization_metadata(
            summary="已写入复权因子 raw 源镜像分区。",
            next_action="等待 raw blocking checks 全部通过；通过后 silver_adj_factor 才能消费。",
            result_status="written",
            input_summary={
                "source": "Tushare adj_factor",
                "partition_key": partition_key,
                "allow_empty": False,
                "target_path_exists": target_path.exists(),
            },
            diagnostic_ref="完整诊断看 raw adj_factor checks、materialization metadata 和 run stdout。",
        )
    )
    log.stdout(
        "raw_adj_factor_completed",
        partition_key=partition_key,
        output_row_count=metadata.get("dagster/row_count"),
        page_count=metadata.get("goldenshare/page_count"),
    )

    return dg.MaterializeResult(metadata=metadata)


@dg.asset(
    name="silver_adj_factor",
    deps=[raw_tushare_adj_factor, silver_stock_lifecycle],
    partitions_def=cn_a_stock_current_trade_days,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.SILVER, data_domain=DataDomain.QUOTE_DATA),
    config_schema={
        "restore_missing_keys": dg.Field(
            [dg.Shape({"ts_code": str, "trade_date": str})],
            default_value=[],
            description="人工旧日定点补缺键；空列表不代表全市场。正常28日起更新不传。",
        ),
    },
    metadata=build_asset_definition_metadata(
        dataset_id="adj_factor",
        source_system=SourceSystem.DERIVED,
        data_contract="standardized_adj_factor",
        column_schema=SILVER_ADJ_FACTOR_SCHEMA,
        path_template=lake_path_template(
            silver_adj_factor_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        extra_metadata={
            "filter_policy": (
                "Keep real Raw factors for known CNY L/D stocks from list_date, "
                "including the delist date and later source records. Normal full "
                "updates start at 2026-10-28; older files require explicit missing keys."
            ),
            "upstream_ready_policy": (
                "silver_stock_lifecycle must exist before silver_adj_factor is "
                "produced; lifecycle is a read-only prerequisite."
            ),
        },
    ),
    description="复权因子Silver标准事实，保留CNY上市及退市股票真实源因子，供复权和指标计算；旧历史仅按明确键补缺。",
)
def silver_adj_factor(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    log = DgStdoutLogger("adj_factor")
    log.stdout(
        "silver_adj_factor_started",
        partition_key=partition_key,
    )
    write_result = write_silver_adj_factor_partition(
        lake_root=lake_root.root(),
        duckdb=duckdb,
        partition_key=partition_key,
        publication_id=context.dagster_run.root_run_id or context.run_id,
        staging_root=Path(DEFAULT_LAKE_STAGING_ROOT),
        overwrite=True,
        restore_missing_keys=context.op_config.get("restore_missing_keys", []),
    )
    extra_metadata = {
        **_human_materialization_metadata(
            summary="已写入复权因子 silver 标准事实分区。",
            next_action="等待 silver blocking checks 全部通过；通过后 qfq 分钟线和指标链路可以消费复权因子。",
            result_status="written",
            input_summary={
                "source_asset": "raw_tushare_adj_factor",
                "supporting_asset": "silver_stock_lifecycle",
                "partition_key": partition_key,
                "raw_file_exists": write_result.raw_file_path.exists(),
                "stock_lifecycle_file_exists": (
                    write_result.stock_lifecycle_file_path.exists()
                ),
            },
            filter_summary={
                "source_row_count": write_result.source_row_count,
                "lifecycle_stock_count": write_result.lifecycle_stock_count,
                "selected_row_count": write_result.selected_row_count,
                "rejected_row_count": write_result.rejected_row_count,
                "output_row_count": write_result.row_count,
                "source_eligible_row_count": write_result.source_eligible_row_count,
                "preserved_row_count": write_result.preserved_row_count,
                "restored_row_count": write_result.restored_row_count,
                "write_mode": write_result.write_mode,
            },
            diagnostic_ref="完整诊断看 silver adj_factor checks、过滤统计 metadata 和 run stdout。",
        ),
        **write_result.materialization_extra_metadata(partition_key),
    }
    log.stdout(
        "silver_adj_factor_completed",
        partition_key=partition_key,
        output_row_count=write_result.row_count,
        selected_row_count=write_result.selected_row_count,
        rejected_row_count=write_result.rejected_row_count,
    )

    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=write_result.silver_file_path,
            row_count=write_result.row_count,
            observed_columns=write_result.observed_columns,
            extra_metadata=extra_metadata,
        )
    )
