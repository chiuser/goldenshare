"""Daily paired assets for stock forward-adjusted trend channels."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import dagster as dg

from orchestrator.defs.assets.calendar import silver_trade_calendar
from orchestrator.defs.assets.stock_basic import silver_stock_basic
from orchestrator.defs.assets.stock_daily_qfq import gold_stock_daily_qfq
from orchestrator.defs.assets.stock_lifecycle import silver_stock_lifecycle
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.partitions import cn_a_stock_daily_trend_channel_trade_days
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    PATH_TEMPLATE_LAKE_ROOT,
    PATH_TEMPLATE_PARTITION_KEY,
    gold_stock_daily_qfq_path,
    gold_stock_daily_trend_channel_path,
    gold_stock_daily_trend_channel_staging_path,
    gold_stock_daily_trend_channel_state_path,
    gold_stock_daily_trend_channel_state_staging_path,
    lake_path_template,
    silver_stock_basic_path,
    silver_stock_lifecycle_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STOCK_DAILY_TREND_CHANNEL_SCHEMA,
    GOLD_STOCK_DAILY_TREND_CHANNEL_STATE_SCHEMA,
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
from orchestrator.defs.stock_daily_trend_channel import (
    FORMULA_KEY,
    FORMULA_VERSION,
    StockDailyTrendChannelWriteResult,
    write_stock_daily_trend_channel_daily_partition,
)

RESULT_ASSET_KEY = "gold_stock_daily_trend_channel"
STATE_ASSET_KEY = "gold_stock_daily_trend_channel_state"


def _shared_dependencies() -> tuple[dg.AssetDep, ...]:
    return (
        dg.AssetDep(
            gold_stock_daily_qfq,
            partition_mapping=dg.IdentityPartitionMapping(),
        ),
        dg.AssetDep(silver_stock_basic),
        dg.AssetDep(silver_stock_lifecycle),
        dg.AssetDep(silver_trade_calendar),
    )


def _result_definition_metadata() -> dict[str, object]:
    return build_asset_definition_metadata(
        dataset_id="stock_daily_trend_channel",
        source_system=SourceSystem.DERIVED,
        data_contract="gold_stock_daily_qfq_trend_channel",
        column_schema=GOLD_STOCK_DAILY_TREND_CHANNEL_SCHEMA,
        path_template=lake_path_template(
            gold_stock_daily_trend_channel_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        extra_metadata={
            "formula_key": FORMULA_KEY,
            "formula_version": FORMULA_VERSION,
            "state_policy": "observed_qfq_rows_only",
        },
    )


def _state_definition_metadata() -> dict[str, object]:
    return build_asset_definition_metadata(
        dataset_id="stock_daily_trend_channel_state",
        source_system=SourceSystem.DERIVED,
        data_contract="gold_stock_daily_qfq_trend_channel_state",
        column_schema=GOLD_STOCK_DAILY_TREND_CHANNEL_STATE_SCHEMA,
        path_template=lake_path_template(
            gold_stock_daily_trend_channel_state_path(
                PATH_TEMPLATE_LAKE_ROOT,
                PATH_TEMPLATE_PARTITION_KEY,
            )
        ),
        extra_metadata={
            "formula_key": FORMULA_KEY,
            "formula_version": FORMULA_VERSION,
            "state_policy": "observed_plus_lifecycle_valid_carry",
        },
    )


@dg.multi_asset(
    name="gold_stock_daily_trend_channel_assets",
    specs=[
        dg.AssetSpec(
            RESULT_ASSET_KEY,
            deps=_shared_dependencies(),
            partitions_def=cn_a_stock_daily_trend_channel_trade_days,
            group_name="quote",
            tags=build_asset_tags(
                layer=AssetLayer.GOLD,
                data_domain=DataDomain.QUOTE_DATA,
            ),
            metadata=_result_definition_metadata(),
            description=(
                "股票日线前复权趋势通道结果；只保存当日存在 qfq 行情的股票。"
            ),
        ),
        dg.AssetSpec(
            STATE_ASSET_KEY,
            deps=_shared_dependencies(),
            partitions_def=cn_a_stock_daily_trend_channel_trade_days,
            group_name="quote",
            tags=build_asset_tags(
                layer=AssetLayer.GOLD,
                data_domain=DataDomain.QUOTE_DATA,
            ),
            metadata=_state_definition_metadata(),
            description=(
                "股票日线前复权趋势通道递推状态；包含当日观测和生命周期内停牌 carry。"
            ),
        ),
    ],
    can_subset=False,
)
def gold_stock_daily_trend_channel_assets(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> Iterator[dg.MaterializeResult]:
    """Materialize result and state together for one expected trade date."""

    lake_root.ensure_available_for_run()
    partition_key = context.partition_key
    root = lake_root.root()
    staging_root = Path(DEFAULT_LAKE_STAGING_ROOT)
    qfq_path = gold_stock_daily_qfq_path(root, partition_key)
    basic_path = silver_stock_basic_path(root)
    lifecycle_path = silver_stock_lifecycle_path(root)
    calendar_path = silver_trade_calendar_path(root)
    if not calendar_path.exists():
        raise FileNotFoundError(f"Missing silver trade calendar file: {calendar_path}")

    with duckdb.connect() as connection:
        previous_trade_date = _load_previous_expected_trade_date(
            connection=connection,
            calendar_path=calendar_path,
            trade_date=partition_key,
        )
        previous_state_path = (
            gold_stock_daily_trend_channel_state_path(root, previous_trade_date)
            if previous_trade_date is not None
            else None
        )
        write_result = write_stock_daily_trend_channel_daily_partition(
            connection=connection,
            trade_date=partition_key,
            qfq_source_path=qfq_path,
            stock_basic_path=basic_path,
            stock_lifecycle_path=lifecycle_path,
            previous_trade_date=previous_trade_date,
            previous_state_path=previous_state_path,
            result_candidate_path=gold_stock_daily_trend_channel_staging_path(
                staging_root,
                context.run_id,
                partition_key,
            ),
            state_candidate_path=(
                gold_stock_daily_trend_channel_state_staging_path(
                    staging_root,
                    context.run_id,
                    partition_key,
                )
            ),
            result_target_path=gold_stock_daily_trend_channel_path(
                root,
                partition_key,
            ),
            state_target_path=gold_stock_daily_trend_channel_state_path(
                root,
                partition_key,
            ),
        )

    yield dg.MaterializeResult(
        asset_key=STATE_ASSET_KEY,
        metadata=_state_materialization_metadata(
            write_result=write_result,
            partition_key=partition_key,
        ),
    )
    yield dg.MaterializeResult(
        asset_key=RESULT_ASSET_KEY,
        metadata=_result_materialization_metadata(
            write_result=write_result,
            partition_key=partition_key,
        ),
    )


def _load_previous_expected_trade_date(
    *,
    connection: Any,
    calendar_path: Path,
    trade_date: str,
) -> str | None:
    date_sql = duckdb_string(trade_date)
    row = connection.execute(
        f"""
        WITH target AS (
          SELECT count(*) AS target_count
          FROM {read_parquet(calendar_path, hive_partitioning=False)}
          WHERE CAST(exchange AS VARCHAR) = 'SSE'
            AND CAST(is_open AS BOOLEAN)
            AND CAST(trade_date AS DATE) = DATE {date_sql}
        ),
        previous AS (
          SELECT strftime(max(CAST(trade_date AS DATE)), '%Y-%m-%d') AS trade_date
          FROM {read_parquet(calendar_path, hive_partitioning=False)}
          WHERE CAST(exchange AS VARCHAR) = 'SSE'
            AND CAST(is_open AS BOOLEAN)
            AND CAST(trade_date AS DATE) < DATE {date_sql}
        )
        SELECT target.target_count, previous.trade_date
        FROM target CROSS JOIN previous
        """
    ).fetchone()
    if int(row[0]) != 1:
        raise ValueError(
            "Stock daily trend-channel partition must be one SSE open date: "
            f"{trade_date}."
        )
    return str(row[1]) if row[1] is not None else None


def _shared_materialization_metadata(
    *,
    write_result: StockDailyTrendChannelWriteResult,
    partition_key: str,
) -> dict[str, object]:
    return {
        "partition_key": partition_key,
        "formula_key": FORMULA_KEY,
        "formula_version": FORMULA_VERSION,
        "qfq_source_path": str(write_result.qfq_source_path),
        "previous_state_path": (
            str(write_result.previous_state_path)
            if write_result.previous_state_path is not None
            else None
        ),
        "stock_basic_path": str(write_result.stock_basic_path),
        "stock_lifecycle_path": str(write_result.stock_lifecycle_path),
        "source_row_count": write_result.source_row_count,
        "observed_state_row_count": write_result.observed_state_row_count,
        "carried_state_row_count": write_result.carried_state_row_count,
        "uninitialized_lifecycle_code_count": (
            write_result.uninitialized_lifecycle_code_count
        ),
        "candidate_bytes": write_result.candidate_bytes,
        "elapsed_ms": round(write_result.elapsed_ms, 3),
        "peak_memory_bytes": write_result.peak_memory_bytes,
        "temp_spill_bytes": write_result.temp_spill_bytes,
    }


def _state_materialization_metadata(
    *,
    write_result: StockDailyTrendChannelWriteResult,
    partition_key: str,
) -> dict[str, object]:
    return build_materialization_metadata(
        uri=write_result.state_path,
        row_count=(
            write_result.observed_state_row_count
            + write_result.carried_state_row_count
        ),
        observed_columns=write_result.observed_state_columns,
        extra_metadata={
            **_shared_materialization_metadata(
                write_result=write_result,
                partition_key=partition_key,
            ),
            "output_row_count": (
                write_result.observed_state_row_count
                + write_result.carried_state_row_count
            ),
            "summary": "已生成股票日线趋势通道递推状态。",
            "next_action": "等待三个 blocking checks 通过后供下一交易日承接。",
        },
    )


def _result_materialization_metadata(
    *,
    write_result: StockDailyTrendChannelWriteResult,
    partition_key: str,
) -> dict[str, object]:
    return build_materialization_metadata(
        uri=write_result.result_path,
        row_count=write_result.output_row_count,
        observed_columns=write_result.observed_result_columns,
        extra_metadata={
            **_shared_materialization_metadata(
                write_result=write_result,
                partition_key=partition_key,
            ),
            "output_row_count": write_result.output_row_count,
            "summary": "已生成股票日线前复权趋势通道结果。",
            "next_action": "等待三个 blocking checks 通过后供下游消费。",
        },
    )
