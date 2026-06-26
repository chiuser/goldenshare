from __future__ import annotations

from datetime import date
from pathlib import Path

import dagster as dg
from dagster import OpExecutionContext

from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.stock_daily_qfq import (
    GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
    build_gold_stock_daily_qfq_factor_repair_check_metadata,
    execute_gold_stock_daily_qfq_factor_repair,
)


GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_CONFIG_SCHEMA = {
    "qfq_factor_trade_date": dg.Field(
        str,
        description="股票日线前复权 repair 的复权因子交易日，格式 YYYY-MM-DD。",
    ),
    "repair_required_codes_hash": dg.Field(
        str,
        description="由相邻 expected trade date 的 silver_adj_factor diff 得到的 affected code 集合 SHA-256。",
    ),
    "upstream_batch_id": dg.Field(
        str,
        description="触发本次 repair 的上游 daily qfq run batch id。",
    ),
}


def _qfq_factor_trade_date_from_config(context: OpExecutionContext) -> str:
    raw_trade_date = str(context.op_config["qfq_factor_trade_date"]).strip()
    try:
        return date.fromisoformat(raw_trade_date).isoformat()
    except ValueError as error:
        raise ValueError("qfq_factor_trade_date must use YYYY-MM-DD format.") from error


def _required_hash_from_config(context: OpExecutionContext) -> str:
    value = str(context.op_config["repair_required_codes_hash"]).strip().lower()
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("repair_required_codes_hash must be a SHA-256 hex string.")
    return value


def _upstream_batch_id_from_config(context: OpExecutionContext) -> str:
    value = str(context.op_config["upstream_batch_id"]).strip()
    if not value:
        raise ValueError("upstream_batch_id must be non-empty.")
    return value


def _load_stock_daily_qfq_expected_trade_dates(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource,
) -> tuple[str, ...]:
    calendar_path = silver_trade_calendar_path(lake_root)
    if not calendar_path.exists():
        raise FileNotFoundError(
            f"silver_trade_calendar file is missing: {calendar_path}"
        )
    with duckdb_resource.connect() as connection:
        rows = connection.execute(
            f"""
            SELECT strftime(CAST(trade_date AS DATE), '%Y-%m-%d') AS trade_date
            FROM {read_parquet(calendar_path, hive_partitioning=False)}
            WHERE CAST(exchange AS VARCHAR) = 'SSE'
              AND CAST(is_open AS BOOLEAN)
              AND CAST(trade_date AS DATE) <= DATE {duckdb_string(date.today().isoformat())}
            ORDER BY CAST(trade_date AS DATE)
            """
        ).fetchall()
    return tuple(str(row[0]) for row in rows)


@dg.op(
    required_resource_keys={"lake_root", "duckdb"},
    config_schema=GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_CONFIG_SCHEMA,
)
def gold_stock_daily_qfq_factor_repair_op(
    context,
) -> None:
    qfq_factor_trade_date = _qfq_factor_trade_date_from_config(context)
    repair_required_codes_hash = _required_hash_from_config(context)
    upstream_batch_id = _upstream_batch_id_from_config(context)
    lake_root_resource = context.resources.lake_root
    lake_root_resource.ensure_available_for_run()
    lake_root = lake_root_resource.root()
    duckdb_resource = context.resources.duckdb
    expected_trade_dates = _load_stock_daily_qfq_expected_trade_dates(
        lake_root=lake_root,
        duckdb_resource=duckdb_resource,
    )

    with duckdb_resource.connect() as connection:
        result = execute_gold_stock_daily_qfq_factor_repair(
            connection=connection,
            lake_root=lake_root,
            qfq_factor_trade_date=qfq_factor_trade_date,
            expected_trade_dates=expected_trade_dates,
            repair_required_codes_hash=repair_required_codes_hash,
            upstream_batch_id=upstream_batch_id,
        )

    metadata = build_gold_stock_daily_qfq_factor_repair_check_metadata(
        result,
        producer_run_id=context.run_id,
    )
    context.log_event(
        dg.AssetCheckEvaluation(
            asset_key=dg.AssetKey("gold_stock_daily_qfq"),
            check_name=GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME,
            passed=True,
            metadata=metadata,
            blocking=True,
            partition=qfq_factor_trade_date,
        )
    )
    context.log.info(
        "Gold stock daily qfq factor repair completed: trade_date=%s reason=%s "
        "repair_required_code_count=%s rewritten_partition_count=%s rewritten_row_count=%s",
        qfq_factor_trade_date,
        result.plan.reason,
        result.plan.repair_required_code_count,
        result.rewritten_partition_count,
        result.rewritten_row_count,
    )
