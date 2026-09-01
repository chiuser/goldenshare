from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import dagster as dg

from orchestrator.defs.asset_guards.stock_daily_qfq_factor_repair import (
    GoldStockDailyQfqFactorRepairStatus,
    gold_stock_daily_qfq_factor_repair_status,
)
from orchestrator.defs.asset_guards.stock_daily_trend_channel_repair import (
    gold_stock_daily_trend_channel_repair_completion_status,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.jobs.gold_stock_daily_qfq_factor_repair import (
    gold_stock_daily_qfq_factor_repair_job,
)
from orchestrator.defs.jobs.gold_stock_daily_trend_channel_repair import (
    gold_stock_daily_trend_channel_repair_job,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, silver_trade_calendar_path
from orchestrator.defs.run_contracts.configs import (
    build_gold_stock_daily_trend_channel_repair_run_config,
)
from orchestrator.defs.run_contracts.cursor_payloads import build_cursor_details
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_upstream_triggered_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE
from orchestrator.defs.stock_daily_trend_channel import (
    FORMULA_VERSION,
    TREND_AUTO_REPAIR_CODE_LIMIT,
)

SENSOR_NAME = "gold_stock_daily_trend_channel_repair_job_sensor"
JOB_NAME = "gold_stock_daily_trend_channel_repair_job"


@dataclass(frozen=True)
class StockDailyTrendChannelRepairRunStatusDecision:
    qfq_factor_repair_trade_date: str | None
    repair_start_trade_date: str | None
    repair_end_trade_date: str | None
    reason_code: str
    reason: str
    next_action: str
    stock_codes: tuple[str, ...] = ()
    repair_required_codes_hash: str | None = None
    source_upstream_batch_id: str | None = None

    @property
    def selected(self) -> bool:
        return self.repair_start_trade_date is not None


def build_stock_daily_trend_channel_repair_run_status_decision(
    *,
    qfq_factor_repair_trade_date: str | None,
    repair_end_trade_date: str | None,
    qfq_factor_repair_status: GoldStockDailyQfqFactorRepairStatus | None,
) -> StockDailyTrendChannelRepairRunStatusDecision:
    if qfq_factor_repair_trade_date is None:
        return StockDailyTrendChannelRepairRunStatusDecision(
            qfq_factor_repair_trade_date=None,
            repair_start_trade_date=None,
            repair_end_trade_date=None,
            reason_code="missing_qfq_factor_repair_trade_date",
            reason="The completed qfq repair run has no valid target trade date.",
            next_action="Inspect the triggering qfq repair run config.",
        )
    status = qfq_factor_repair_status
    if status is None or not status.ready:
        return StockDailyTrendChannelRepairRunStatusDecision(
            qfq_factor_repair_trade_date=qfq_factor_repair_trade_date,
            repair_start_trade_date=None,
            repair_end_trade_date=repair_end_trade_date,
            reason_code="qfq_repair_status_not_ready",
            reason=(
                status.reason
                if status is not None
                else "The exact qfq repair status is unavailable."
            ),
            next_action="Restore the exact qfq factor repair completion check.",
        )
    if not status.repair_required:
        return StockDailyTrendChannelRepairRunStatusDecision(
            qfq_factor_repair_trade_date=qfq_factor_repair_trade_date,
            repair_start_trade_date=None,
            repair_end_trade_date=repair_end_trade_date,
            reason_code="trend_repair_not_required",
            reason="The qfq reconciliation found no factor changes.",
            next_action="No trend repair is needed; the daily sensor may continue.",
        )
    if (
        status.repair_required_code_count > TREND_AUTO_REPAIR_CODE_LIMIT
        or status.repair_required_codes_truncated
    ):
        return StockDailyTrendChannelRepairRunStatusDecision(
            qfq_factor_repair_trade_date=qfq_factor_repair_trade_date,
            repair_start_trade_date=None,
            repair_end_trade_date=repair_end_trade_date,
            reason_code="repair_scope_exceeds_auto_limit",
            reason="The affected stock scope exceeds the automatic trend repair limit.",
            next_action="Run a separately approved dry-run and manual scoped repair.",
        )
    if (
        repair_end_trade_date is None
        or status.repair_start_trade_date is None
        or status.repair_required_codes_hash is None
        or status.upstream_batch_id is None
        or status.selected_partition_count <= 0
        or status.repair_end_trade_date != qfq_factor_repair_trade_date
        or len(status.repair_required_codes) != status.repair_required_code_count
        or status.repair_required_code_count <= 0
    ):
        return StockDailyTrendChannelRepairRunStatusDecision(
            qfq_factor_repair_trade_date=qfq_factor_repair_trade_date,
            repair_start_trade_date=None,
            repair_end_trade_date=repair_end_trade_date,
            reason_code="qfq_repair_scope_invalid",
            reason="The qfq repair metadata does not contain one exact repair scope.",
            next_action="Fix the qfq repair count, range, code list, hash or batch metadata.",
        )
    return StockDailyTrendChannelRepairRunStatusDecision(
        qfq_factor_repair_trade_date=qfq_factor_repair_trade_date,
        repair_start_trade_date=status.repair_start_trade_date,
        repair_end_trade_date=repair_end_trade_date,
        reason_code="selected_for_trend_repair",
        reason="The exact qfq repair scope requires a trend-channel repair.",
        next_action="Submit the scoped repair and wait for both completion checks.",
        stock_codes=status.repair_required_codes,
        repair_required_codes_hash=status.repair_required_codes_hash,
        source_upstream_batch_id=status.upstream_batch_id,
    )


def _qfq_config_from_run(
    dagster_run: dg.DagsterRun,
) -> tuple[str | None, str | None]:
    run_config = dagster_run.run_config
    if not isinstance(run_config, Mapping):
        return None, None
    ops = run_config.get("ops")
    if not isinstance(ops, Mapping):
        return None, None
    op_config = ops.get("gold_stock_daily_qfq_factor_repair_op")
    if not isinstance(op_config, Mapping):
        return None, None
    config = op_config.get("config")
    if not isinstance(config, Mapping):
        return None, None
    trade_date = str(config.get("qfq_factor_trade_date") or "").strip()
    upstream_batch_id = str(config.get("upstream_batch_id") or "").strip()
    return trade_date or None, upstream_batch_id or None


def _previous_expected_trade_date(trade_date: str) -> str | None:
    lake_root = Path(DEFAULT_LAKE_ROOT)
    calendar_path = silver_trade_calendar_path(lake_root)
    if not calendar_path.is_file():
        return None
    with connect_configured_duckdb() as connection:
        row = connection.execute(
            f"""
            SELECT strftime(max(CAST(trade_date AS DATE)), '%Y-%m-%d')
            FROM {read_parquet(calendar_path, hive_partitioning=False)}
            WHERE CAST(exchange AS VARCHAR) = 'SSE'
              AND CAST(is_open AS BOOLEAN)
              AND CAST(trade_date AS DATE) < DATE {duckdb_string(trade_date)}
            """
        ).fetchone()
    return str(row[0]) if row and row[0] is not None else None


def _run_request(
    decision: StockDailyTrendChannelRepairRunStatusDecision,
) -> dg.RunRequest:
    if (
        not decision.selected
        or decision.qfq_factor_repair_trade_date is None
        or decision.repair_end_trade_date is None
        or decision.repair_required_codes_hash is None
        or decision.source_upstream_batch_id is None
    ):
        raise ValueError("Trend-channel repair decision is not runnable.")
    return build_run_request(
        run_key=build_upstream_triggered_run_key(
            consumer=f"gold_stock_daily_trend_channel_repair:{FORMULA_VERSION}",
            upstream_batch_id=decision.source_upstream_batch_id,
        ),
        run_config=build_gold_stock_daily_trend_channel_repair_run_config(
            qfq_factor_repair_trade_date=(decision.qfq_factor_repair_trade_date),
            repair_start_trade_date=decision.repair_start_trade_date,
            repair_end_trade_date=decision.repair_end_trade_date,
            stock_codes=decision.stock_codes,
            repair_required_codes_hash=decision.repair_required_codes_hash,
            source_upstream_batch_id=decision.source_upstream_batch_id,
        ),
    )


def _cursor(
    decision: StockDailyTrendChannelRepairRunStatusDecision,
) -> str:
    return build_sensor_cursor(
        evaluated_at=datetime.now(CN_A_SENSOR_TIMEZONE),
        decision=(
            SensorCursorDecision.REQUEST_RUNS
            if decision.selected
            else SensorCursorDecision.SKIP
        ),
        target_date=decision.qfq_factor_repair_trade_date,
        selected_count=1 if decision.selected else 0,
        blocked_count=(
            1
            if decision.reason_code
            in {"repair_scope_exceeds_auto_limit", "qfq_repair_scope_invalid"}
            else 0
        ),
        sample_keys=(
            (decision.qfq_factor_repair_trade_date,)
            if decision.qfq_factor_repair_trade_date
            else ()
        ),
        details=build_cursor_details(
            sensor_name=SENSOR_NAME,
            job_name=JOB_NAME,
            asset_family="stock_daily_trend_channel",
            reason_code=decision.reason_code,
            blocked_component=("none" if decision.selected else decision.reason_code),
            summary=decision.reason,
            next_action=decision.next_action,
            evidence={
                "repair_start_trade_date": decision.repair_start_trade_date,
                "repair_end_trade_date": decision.repair_end_trade_date,
                "repair_required_code_count": len(decision.stock_codes),
                "repair_required_codes_hash": decision.repair_required_codes_hash,
                "source_upstream_batch_id": decision.source_upstream_batch_id,
                "formula_version": FORMULA_VERSION,
            },
        ),
    )


def _evaluate_sensor(
    context: dg.RunStatusSensorContext,
) -> dg.SensorResult:
    trade_date, upstream_batch_id = _qfq_config_from_run(context.dagster_run)
    repair_end_trade_date = (
        _previous_expected_trade_date(trade_date) if trade_date is not None else None
    )
    status = (
        gold_stock_daily_qfq_factor_repair_status(
            context.instance,
            trade_date,
            upstream_batch_id=upstream_batch_id,
        )
        if trade_date is not None and upstream_batch_id is not None
        else None
    )
    decision = build_stock_daily_trend_channel_repair_run_status_decision(
        qfq_factor_repair_trade_date=trade_date,
        repair_end_trade_date=repair_end_trade_date,
        qfq_factor_repair_status=status,
    )
    if not decision.selected:
        return dg.SensorResult(
            skip_reason=f"{decision.reason_code}: {decision.reason}",
            cursor=_cursor(decision),
        )
    assert status is not None
    completion = gold_stock_daily_trend_channel_repair_completion_status(
        context.instance,
        qfq_factor_repair_trade_date=trade_date,
        repair_start_trade_date=decision.repair_start_trade_date,
        repair_end_trade_date=decision.repair_end_trade_date,
        selected_partition_count=max(status.selected_partition_count - 1, 0),
        repair_required_code_count=status.repair_required_code_count,
        repair_required_codes_hash=decision.repair_required_codes_hash,
        source_upstream_batch_id=decision.source_upstream_batch_id,
    )
    if completion.ready:
        completed_decision = StockDailyTrendChannelRepairRunStatusDecision(
            qfq_factor_repair_trade_date=trade_date,
            repair_start_trade_date=None,
            repair_end_trade_date=decision.repair_end_trade_date,
            reason_code="trend_repair_completion_ready",
            reason=completion.reason,
            next_action="No duplicate trend repair run is needed.",
        )
        return dg.SensorResult(
            skip_reason=completed_decision.reason,
            cursor=_cursor(completed_decision),
        )
    return dg.SensorResult(
        run_requests=[_run_request(decision)],
        cursor=_cursor(decision),
    )


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    request_job=gold_stock_daily_trend_channel_repair_job,
    monitored_jobs=[gold_stock_daily_qfq_factor_repair_job],
    default_status=dg.DefaultSensorStatus.STOPPED,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
    description=(
        "qfq factor repair 成功后，按 exact batch 和完整 affected codes 自动提交股票日线"
        "趋势通道 scoped repair；超过 500 个代码时 fail closed。"
    ),
)
def gold_stock_daily_trend_channel_repair_job_sensor(
    context: dg.RunStatusSensorContext,
) -> dg.SensorResult:
    return _evaluate_sensor(context)
