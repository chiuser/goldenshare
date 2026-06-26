import dagster as dg

from orchestrator.defs.partitions import cn_a_stock_mins_silver_trade_days
from orchestrator.defs.paths import (
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    gold_wealth_market_turnover_path,
    lake_path_template,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_WEALTH_MARKET_TURNOVER_SCHEMA,
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
from orchestrator.defs.wealth_market_turnover_contract import (
    GOLD_WEALTH_MARKET_TURNOVER_COLUMNS,
    STK_MINS_FREQS,
    wealth_market_turnover_input_paths,
    write_gold_wealth_market_turnover_partition,
)
from orchestrator.utils.dg_log_helper import DgStdoutLogger


def _human_materialization_metadata(
    *,
    partition_key: str,
    input_path_count: int,
    audit,
) -> dict[str, object]:
    return {
        "summary": "已生成财富端市场成交额 gold 快照，按 1/5/15/30/60 分钟五频度输出 points_json。",
        "next_action": "等待 gold_wealth_market_turnover_integrity_check 通过；通过后同一个 job 会同步 prod core serving。",
        "result_status": "written",
        "input_summary": {
            "source_asset_family": "silver_stk_mins",
            "partition_key": partition_key,
            "freqs": list(STK_MINS_FREQS),
            "input_file_count": input_path_count,
        },
        "metric_summary": {
            "output_row_count": audit.row_count,
            "source_row_count": audit.source_row_count,
            "total_amount": audit.total_amount,
            "total_vol": audit.total_vol,
            "security_count_by_freq": audit.security_count_by_freq,
        },
        "diagnostic_ref": "完整诊断看 gold_wealth_market_turnover_integrity_check、points_json hash 和 run stdout。",
    }


@dg.asset(
    name="gold_wealth_market_turnover",
    deps=[
        "silver_stk_mins_1m",
        "silver_stk_mins_5m",
        "silver_stk_mins_15m",
        "silver_stk_mins_30m",
        "silver_stk_mins_60m",
    ],
    partitions_def=cn_a_stock_mins_silver_trade_days,
    group_name="wealth",
    tags=build_asset_tags(layer=AssetLayer.GOLD, data_domain=DataDomain.DERIVED_METRIC),
    metadata=build_asset_definition_metadata(
        dataset_id="wealth_market_turnover",
        source_system=SourceSystem.DERIVED,
        data_contract="wealth_market_turnover_snapshot",
        source_doc="wealth/docs/pages/market-overview/turnover-minute-snapshot-plan-v1.html",
        path_template=lake_path_template(
            gold_wealth_market_turnover_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        column_schema=GOLD_WEALTH_MARKET_TURNOVER_SCHEMA,
        extra_metadata={
            "calculation_contract": (
                "source=silver_stk_mins; freqs=1/5/15/30/60; "
                "amount is converted from yuan to thousand_yuan; "
                "points_json stores the full minute point array."
            )
        },
    ),
    description="财富端市场成交额 gold 快照，从 silver_stk_mins 五频度生成 points_json，供财富市场总览和 prod core serving 消费。",
)
def gold_wealth_market_turnover(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    input_paths = wealth_market_turnover_input_paths(lake_root.root(), partition_key)
    target_path = gold_wealth_market_turnover_path(lake_root.root(), partition_key)
    log = DgStdoutLogger("wealth_market_turnover")
    log.stdout(
        "gold_wealth_market_turnover_started",
        partition_key=partition_key,
        freq_count=len(STK_MINS_FREQS),
    )

    audit = write_gold_wealth_market_turnover_partition(
        duckdb_resource=duckdb,
        input_paths=input_paths,
        partition_key=partition_key,
        target_path=target_path,
    )
    log.stdout(
        "gold_wealth_market_turnover_completed",
        partition_key=partition_key,
        output_row_count=audit.row_count,
        source_row_count=audit.source_row_count,
        freq_count=len(STK_MINS_FREQS),
    )

    return dg.MaterializeResult(
        metadata=build_materialization_metadata(
            uri=target_path,
            row_count=audit.row_count,
            observed_columns=audit.observed_columns,
            extra_metadata={
                **_human_materialization_metadata(
                    partition_key=partition_key,
                    input_path_count=len(input_paths),
                    audit=audit,
                ),
                "partition_key": partition_key,
                "input_file_paths": [str(input_path.path) for input_path in input_paths],
                "freqs": list(STK_MINS_FREQS),
                "build_version": "v1",
                "source_row_count": audit.source_row_count,
                "total_amount": audit.total_amount,
                "total_vol": audit.total_vol,
                "security_count_by_freq": audit.security_count_by_freq,
                "latest_trade_time_by_freq": audit.latest_trade_time_by_freq,
            },
        )
    )


WEALTH_MARKET_TURNOVER_COLUMNS = GOLD_WEALTH_MARKET_TURNOVER_COLUMNS
