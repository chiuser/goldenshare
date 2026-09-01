from pathlib import Path

import dagster as dg

from orchestrator.defs.asset_guards.stock_daily_qfq_factor_repair import (
    GoldStockDailyQfqFactorRepairStatus,
    gold_stock_daily_qfq_factor_repair_status,
)
from orchestrator.defs.asset_guards.stock_daily_trend_channel_repair import (
    RESULT_ASSET_KEY,
    RESULT_REPAIR_COMPLETION_CHECK_NAME,
    STATE_ASSET_KEY,
    STATE_REPAIR_COMPLETION_CHECK_NAME,
)
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    gold_stock_daily_qfq_path,
    gold_stock_daily_trend_channel_path,
    gold_stock_daily_trend_channel_staging_path,
    gold_stock_daily_trend_channel_state_path,
    gold_stock_daily_trend_channel_state_staging_path,
    silver_stock_lifecycle_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.configs import (
    GoldStockDailyTrendChannelRepairConfig,
)
from orchestrator.defs.run_contracts.metadata import CheckScope, build_check_metadata
from orchestrator.defs.stock_daily_qfq import (
    gold_stock_daily_qfq_factor_repair_codes_hash,
)
from orchestrator.defs.stock_daily_trend_channel import (
    FORMULA_VERSION,
    TREND_AUTO_REPAIR_CODE_LIMIT,
    StockDailyTrendChannelRepairPartition,
    StockDailyTrendChannelRepairResult,
    write_stock_daily_trend_channel_factor_repair,
)


def _load_expected_trade_dates(
    *,
    connection,
    calendar_path: Path,
    end_trade_date: str,
) -> tuple[str, ...]:
    if not calendar_path.is_file():
        raise FileNotFoundError(
            f"silver_trade_calendar file is missing: {calendar_path}"
        )
    rows = connection.execute(
        f"""
        SELECT strftime(CAST(trade_date AS DATE), '%Y-%m-%d')
        FROM {read_parquet(calendar_path, hive_partitioning=False)}
        WHERE CAST(exchange AS VARCHAR) = 'SSE'
          AND CAST(is_open AS BOOLEAN)
          AND CAST(trade_date AS DATE) <= DATE {duckdb_string(end_trade_date)}
        ORDER BY CAST(trade_date AS DATE)
        """
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _trend_repair_trade_dates(
    *,
    expected_trade_dates: tuple[str, ...],
    repair_start_trade_date: str,
    qfq_factor_repair_trade_date: str,
) -> tuple[str, tuple[str, ...]]:
    if qfq_factor_repair_trade_date not in expected_trade_dates:
        raise dg.Failure(
            "qfq_factor_repair_trade_date is not an expected stock trade date."
        )
    qfq_index = expected_trade_dates.index(qfq_factor_repair_trade_date)
    if qfq_index == 0:
        raise dg.Failure(
            "Trend-channel repair cannot derive a previous expected trade date."
        )
    repair_end_trade_date = expected_trade_dates[qfq_index - 1]
    target_dates = tuple(
        trade_date
        for trade_date in expected_trade_dates
        if repair_start_trade_date <= trade_date <= repair_end_trade_date
    )
    if target_dates and target_dates[0] != repair_start_trade_date:
        raise dg.Failure(
            "Trend-channel repair start date is not an expected stock trade date."
        )
    return repair_end_trade_date, target_dates


def _validated_qfq_repair_status(
    *,
    instance: dg.DagsterInstance,
    config: GoldStockDailyTrendChannelRepairConfig,
) -> GoldStockDailyQfqFactorRepairStatus:
    status = gold_stock_daily_qfq_factor_repair_status(
        instance,
        config.qfq_factor_repair_trade_date,
        upstream_batch_id=config.source_upstream_batch_id,
    )
    normalized_codes = tuple(str(code).strip().upper() for code in config.stock_codes)
    if not status.ready or not status.repair_required:
        raise dg.Failure(
            "Trend-channel repair requires a ready qfq factor repair scope: "
            f"reason={status.reason}."
        )
    if (
        status.repair_start_trade_date != config.repair_start_trade_date
        or status.repair_end_trade_date != config.qfq_factor_repair_trade_date
        or status.repair_required_codes != normalized_codes
        or status.repair_required_code_count != len(normalized_codes)
        or status.repair_required_codes_hash != config.repair_required_codes_hash
        or status.upstream_batch_id != config.source_upstream_batch_id
        or status.repair_required_codes_truncated
        or len(normalized_codes) > TREND_AUTO_REPAIR_CODE_LIMIT
        or gold_stock_daily_qfq_factor_repair_codes_hash(normalized_codes)
        != config.repair_required_codes_hash
    ):
        raise dg.Failure(
            "Trend-channel repair config does not match the exact qfq repair metadata."
        )
    return status


def _repair_partitions(
    *,
    lake_root: Path,
    staging_root: Path,
    run_id: str,
    target_dates: tuple[str, ...],
    expected_trade_dates: tuple[str, ...],
) -> tuple[StockDailyTrendChannelRepairPartition, ...]:
    expected_indexes = {
        trade_date: index for index, trade_date in enumerate(expected_trade_dates)
    }
    return tuple(
        StockDailyTrendChannelRepairPartition(
            trade_date=trade_date,
            qfq_source_path=gold_stock_daily_qfq_path(lake_root, trade_date),
            previous_state_target_path=(
                gold_stock_daily_trend_channel_state_path(
                    lake_root,
                    expected_trade_dates[expected_indexes[trade_date] - 1],
                )
                if expected_indexes[trade_date] > 0
                else None
            ),
            result_target_path=gold_stock_daily_trend_channel_path(
                lake_root,
                trade_date,
            ),
            state_target_path=gold_stock_daily_trend_channel_state_path(
                lake_root,
                trade_date,
            ),
            result_candidate_path=gold_stock_daily_trend_channel_staging_path(
                staging_root,
                run_id,
                trade_date,
            ),
            state_candidate_path=(
                gold_stock_daily_trend_channel_state_staging_path(
                    staging_root,
                    run_id,
                    trade_date,
                )
            ),
        )
        for trade_date in target_dates
    )


def _completion_metadata(
    *,
    result: StockDailyTrendChannelRepairResult,
    qfq_factor_repair_trade_date: str,
    repair_required_codes_hash: str,
    source_upstream_batch_id: str,
    producer_run_id: str,
) -> dict[str, object]:
    selected_partition_count = result.selected_partition_count
    return build_check_metadata(
        check_scope=CheckScope.RECONCILIATION,
        checked_row_count=(
            result.rewritten_result_row_count + result.rewritten_state_row_count
        ),
        failed_row_count=0,
        extra_metadata={
            "summary": (
                "Stock daily trend-channel factor repair completed for "
                f"{selected_partition_count} partitions."
            ),
            "next_action": (
                "Wait for the daily trend-channel sensor to consume this exact "
                "upstream batch completion."
            ),
            "qfq_factor_repair_trade_date": qfq_factor_repair_trade_date,
            "repair_start_trade_date": result.repair_start_trade_date,
            "repair_end_trade_date": result.repair_end_trade_date,
            "covered_start_trade_date": result.repair_start_trade_date,
            "covered_end_trade_date": result.repair_end_trade_date,
            "selected_partition_count": selected_partition_count,
            "repair_required_code_count": result.repair_required_code_count,
            "repair_required_codes_hash": repair_required_codes_hash,
            "source_upstream_batch_id": source_upstream_batch_id,
            "formula_version": FORMULA_VERSION,
            "rewritten_partition_count": selected_partition_count,
            "rewritten_indicator_partition_count": (
                result.rewritten_result_partition_count
            ),
            "rewritten_result_partition_count": (
                result.rewritten_result_partition_count
            ),
            "rewritten_state_partition_count": (result.rewritten_state_partition_count),
            "rewritten_indicator_row_count": result.rewritten_result_row_count,
            "rewritten_result_row_count": result.rewritten_result_row_count,
            "rewritten_state_row_count": result.rewritten_state_row_count,
            "producer_run_id": producer_run_id,
            "temp_spill_bytes": result.temp_spill_bytes,
            "elapsed_ms": result.elapsed_ms,
        },
    )


@dg.op(required_resource_keys={"lake_root", "duckdb"})
def gold_stock_daily_trend_channel_repair_op(
    context: dg.OpExecutionContext,
    config: GoldStockDailyTrendChannelRepairConfig,
) -> None:
    context.resources.lake_root.ensure_available_for_run()
    lake_root = context.resources.lake_root.root()
    staging_root = Path(DEFAULT_LAKE_STAGING_ROOT)
    status = _validated_qfq_repair_status(
        instance=context.instance,
        config=config,
    )

    with context.resources.duckdb.connect() as connection:
        expected_trade_dates = _load_expected_trade_dates(
            connection=connection,
            calendar_path=silver_trade_calendar_path(lake_root),
            end_trade_date=config.qfq_factor_repair_trade_date,
        )
        repair_end_trade_date, target_dates = _trend_repair_trade_dates(
            expected_trade_dates=expected_trade_dates,
            repair_start_trade_date=config.repair_start_trade_date,
            qfq_factor_repair_trade_date=config.qfq_factor_repair_trade_date,
        )
        if config.repair_end_trade_date != repair_end_trade_date:
            raise dg.Failure(
                "Trend-channel repair end date must be the previous expected trade date."
            )
        if status.selected_partition_count != len(target_dates) + 1:
            raise dg.Failure(
                "Trend-channel repair date count does not match qfq repair metadata."
            )
        result = write_stock_daily_trend_channel_factor_repair(
            connection=connection,
            repair_start_trade_date=config.repair_start_trade_date,
            repair_end_trade_date=config.repair_end_trade_date,
            repair_required_codes=config.stock_codes,
            stock_lifecycle_path=silver_stock_lifecycle_path(lake_root),
            partitions=_repair_partitions(
                lake_root=lake_root,
                staging_root=staging_root,
                run_id=context.run_id,
                target_dates=target_dates,
                expected_trade_dates=expected_trade_dates,
            ),
        )

    metadata = _completion_metadata(
        result=result,
        qfq_factor_repair_trade_date=config.qfq_factor_repair_trade_date,
        repair_required_codes_hash=config.repair_required_codes_hash,
        source_upstream_batch_id=config.source_upstream_batch_id,
        producer_run_id=context.run_id,
    )
    for asset_key, check_name in (
        (RESULT_ASSET_KEY, RESULT_REPAIR_COMPLETION_CHECK_NAME),
        (STATE_ASSET_KEY, STATE_REPAIR_COMPLETION_CHECK_NAME),
    ):
        context.log_event(
            dg.AssetCheckEvaluation(
                asset_key=asset_key,
                check_name=check_name,
                passed=True,
                metadata=metadata,
                blocking=True,
                partition=config.qfq_factor_repair_trade_date,
            )
        )
    context.log.info(
        "Stock daily trend-channel repair completed: qfq_factor_trade_date=%s "
        "repair_start=%s repair_end=%s code_count=%s partition_count=%s",
        config.qfq_factor_repair_trade_date,
        result.repair_start_trade_date,
        result.repair_end_trade_date,
        result.repair_required_code_count,
        result.selected_partition_count,
    )
