import dagster as dg

from orchestrator.defs.assets.adj_factor import silver_adj_factor
from orchestrator.defs.assets.stock_daily import silver_stock_daily
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    gold_stock_daily_qfq_path,
    lake_path_template,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STOCK_DAILY_QFQ_SCHEMA,
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
from orchestrator.defs.stock_daily_qfq import (
    load_stock_daily_qfq_previous_lookup_trade_dates,
    write_gold_stock_daily_qfq_partition,
)


@dg.asset(
    name="gold_stock_daily_qfq",
    partitions_def=cn_a_stock_trade_days,
    deps=[silver_stock_daily, silver_adj_factor],
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.GOLD, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(
        dataset_id="stock_daily_qfq",
        source_system=SourceSystem.DERIVED,
        data_contract="gold_stock_daily_forward_adjusted_quote",
        column_schema=GOLD_STOCK_DAILY_QFQ_SCHEMA,
        path_template=lake_path_template(
            gold_stock_daily_qfq_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        extra_metadata={
            "formula_policy": (
                "Forward-adjusted prices use source_price * trade_date_adj_factor / "
                "as_of_adj_factor. Daily runs use as_of_trade_date=partition_key."
            ),
            "previous_close_policy": (
                "pre_close/change_amount/pct_chg are recomputed from the previous "
                "available silver_stock_daily row for each stock. If no previous "
                "source row exists, all three fields are written as 0."
            ),
        },
    ),
    description=(
        "股票日线 gold 前复权行情事实，基于 silver_stock_daily 与 "
        "silver_adj_factor 生成，供长期均线、日线指标和研究消费。"
    ),
)
def gold_stock_daily_qfq(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    root = lake_root.root()
    connect_duckdb = duckdb.connect
    connection_context = connect_duckdb()
    with connection_context as connection:
        previous_lookup_trade_dates = load_stock_daily_qfq_previous_lookup_trade_dates(
            connection=connection,
            lake_root=root,
            trade_date=partition_key,
        )
        result = write_gold_stock_daily_qfq_partition(
            connection=connection,
            lake_root=root,
            trade_date=partition_key,
            previous_lookup_trade_dates=previous_lookup_trade_dates,
        )

    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=result.path,
            row_count=result.output_row_count,
            observed_columns=result.observed_columns,
            extra_metadata={
                "partition_key": partition_key,
                "source_silver_stock_daily_file_path": str(
                    result.stock_daily_file_path
                ),
                "source_silver_adj_factor_file_path": str(
                    result.trade_adj_factor_file_path
                ),
                "as_of_adj_factor_file_path": str(result.as_of_adj_factor_file_path),
                "previous_lookup_trade_date_count": (
                    result.previous_lookup_trade_date_count
                ),
                "previous_stock_daily_file_count": (
                    result.previous_stock_daily_file_count
                ),
                "previous_adj_factor_file_count": result.previous_adj_factor_file_count,
                "missing_previous_row_count": result.missing_previous_row_count,
                "source_row_count": result.source_row_count,
            },
        )
    )
