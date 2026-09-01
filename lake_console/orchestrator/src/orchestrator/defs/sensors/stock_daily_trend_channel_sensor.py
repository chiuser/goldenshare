"""Daily readiness sensor for stock forward-adjusted trend channels."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import dagster as dg
import duckdb

from orchestrator.defs.asset_guards.bounded_continuity import (
    DEFAULT_CONTINUITY_WINDOW_LIMIT,
    ContinuityDateReadiness,
    ContinuityExpectedDateWindow,
    ContinuityRegisteredGapStatus,
    build_registered_gap_status,
    load_expected_trade_date_window,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.asset_guards.stock_daily_qfq_factor_repair import (
    GoldStockDailyQfqFactorRepairStatus,
    gold_stock_daily_qfq_factor_repair_status,
)
from orchestrator.defs.asset_guards.stock_daily_trend_channel_lake_readiness import (
    StockDailyTrendChannelBatchReadiness,
    batch_gold_stock_daily_trend_channel_readiness,
)
from orchestrator.defs.duckdb_sql import duckdb_string, read_parquet
from orchestrator.defs.jobs.stock_daily_trend_channel_update import (
    gold_stock_daily_trend_channel_update_job,
)
from orchestrator.defs.partitions import (
    cn_a_stock_daily_trend_channel_trade_days,
)
from orchestrator.defs.paths import (
    gold_stock_daily_trend_channel_state_path,
    silver_adj_factor_path,
    silver_stock_lifecycle_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.cursor_payloads import (
    build_cursor_details,
    compact_batch_frontier,
    compact_continuity_frontier,
    compact_gate_statuses,
)
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.gold_stock_daily_qfq_factor_repair_job_sensor import (
    build_gold_stock_daily_qfq_factor_repair_upstream_batch_id,
)
from orchestrator.defs.sensors.readiness import (
    CN_A_SENSOR_TIMEZONE,
    GOLD_STOCK_DAILY_QFQ_ASSET_KEY,
    GOLD_STOCK_DAILY_QFQ_READINESS_SPECS,
    partition_dataset_readiness_status_from_latest_checks,
    silver_stock_lifecycle_ready_for_trade_date,
    stock_basic_ready_for_trade_date,
)
from orchestrator.defs.stock_daily_qfq import (
    GoldStockDailyQfqFactorRepairPlan,
    build_gold_stock_daily_qfq_factor_repair_plan,
)
from orchestrator.defs.stock_daily_trend_channel import (
    FORMULA_VERSION,
    audit_stock_daily_trend_channel_state,
)

GOLD_STOCK_DAILY_TREND_CHANNEL_SENSOR_NAME = (
    "gold_stock_daily_trend_channel_update_job_sensor"
)
GOLD_STOCK_DAILY_TREND_CHANNEL_JOB_NAME = (
    "gold_stock_daily_trend_channel_update_job"
)


def _load_expected_window(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime,
) -> ContinuityExpectedDateWindow:
    lake_root = context.resources.lake_root
    duckdb_resource = context.resources.duckdb
    lake_root.ensure_available_for_run()
    root = lake_root.root()
    calendar_path = silver_trade_calendar_path(root)
    if not calendar_path.is_file():
        raise FileNotFoundError(
            f"silver_trade_calendar file is missing: {calendar_path}"
        )
    with duckdb_resource.connect() as connection:
        return load_expected_trade_date_window(
            connection,
            calendar_path,
            evaluated_at=evaluated_at,
            window_limit=DEFAULT_CONTINUITY_WINDOW_LIMIT,
        )


def _load_target_readiness(
    context: dg.SensorEvaluationContext,
    *,
    actionable_trade_dates: tuple[str, ...],
) -> tuple[str | None, StockDailyTrendChannelBatchReadiness]:
    lake_root = context.resources.lake_root
    duckdb_resource = context.resources.duckdb
    root = lake_root.root()
    calendar_path = silver_trade_calendar_path(root)
    with duckdb_resource.connect() as connection:
        previous_trade_date = _load_previous_expected_trade_date(
            connection=connection,
            calendar_path=calendar_path,
            trade_date=(
                actionable_trade_dates[0] if actionable_trade_dates else None
            ),
        )
        batch_status = batch_gold_stock_daily_trend_channel_readiness(
            connection=connection,
            lake_root=root,
            expected_trade_dates=actionable_trade_dates,
            previous_trade_date=previous_trade_date,
        )
    return previous_trade_date, batch_status


def _load_previous_expected_trade_date(
    *,
    connection,
    calendar_path: Path,
    trade_date: str | None,
) -> str | None:
    if trade_date is None:
        return None
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


def _previous_state_status(
    context: dg.SensorEvaluationContext,
    *,
    target_trade_date: str,
    previous_trade_date: str | None,
) -> ContinuityDateReadiness | None:
    if previous_trade_date is None:
        return None
    root = context.resources.lake_root.root()
    state_path = gold_stock_daily_trend_channel_state_path(
        root,
        previous_trade_date,
    )
    lifecycle_path = silver_stock_lifecycle_path(root)
    with context.resources.duckdb.connect() as connection:
        audit = audit_stock_daily_trend_channel_state(
            connection=connection,
            state_path=state_path,
            stock_lifecycle_path=lifecycle_path,
            trade_date=previous_trade_date,
        )
    return ContinuityDateReadiness(
        trade_date=target_trade_date,
        ready=audit.passed,
        materialized=state_path.is_file(),
        checks_passed=audit.passed,
        reason="ready" if audit.passed else "previous_state_not_ready",
        failed_check_names=(
            ()
            if audit.passed
            else ("gold_stock_daily_trend_channel_state_contract_check",)
        ),
        missing_file_paths=(() if state_path.is_file() else (str(state_path),)),
        summary={
            "previous_trade_date": previous_trade_date,
            "failure_rule_counts": dict(audit.failure_rule_counts),
        },
    )


def _latest_qfq_materialization_run_id(
    instance: dg.DagsterInstance,
    trade_date: str,
) -> str | None:
    records = instance.fetch_materializations(
        dg.AssetRecordsFilter(
            asset_key=GOLD_STOCK_DAILY_QFQ_ASSET_KEY,
            asset_partitions=[trade_date],
        ),
        limit=1,
    ).records
    if not records:
        return None
    run_id = str(getattr(records[0], "run_id", "") or "").strip()
    return run_id or None


def _qfq_reconciliation(
    context: dg.SensorEvaluationContext,
    *,
    target_trade_date: str,
    previous_trade_date: str | None,
) -> tuple[
    GoldStockDailyQfqFactorRepairPlan | None,
    GoldStockDailyQfqFactorRepairStatus | None,
    str | None,
]:
    producer_run_id = _latest_qfq_materialization_run_id(
        context.instance,
        target_trade_date,
    )
    if producer_run_id is None:
        return None, None, "qfq_materialization_run_id_missing"
    root = context.resources.lake_root.root()
    current_adj_factor_path = silver_adj_factor_path(root, target_trade_date)
    previous_adj_factor_path = (
        silver_adj_factor_path(root, previous_trade_date)
        if previous_trade_date is not None
        else None
    )
    required_paths = (current_adj_factor_path,) + (
        (previous_adj_factor_path,) if previous_adj_factor_path is not None else ()
    )
    if any(not path.is_file() for path in required_paths):
        return None, None, "qfq_factor_input_missing"
    try:
        with context.resources.duckdb.connect() as connection:
            plan = build_gold_stock_daily_qfq_factor_repair_plan(
                connection=connection,
                current_adj_factor_path=current_adj_factor_path,
                previous_adj_factor_path=previous_adj_factor_path,
                qfq_factor_trade_date=target_trade_date,
                previous_trade_date=previous_trade_date,
            )
    except (duckdb.Error, ValueError):
        return None, None, "qfq_factor_plan_failed"
    upstream_batch_id = (
        build_gold_stock_daily_qfq_factor_repair_upstream_batch_id(
            producer_run_id=producer_run_id,
            target_trade_date=target_trade_date,
            repair_required_codes_hash=plan.repair_required_codes_hash,
        )
    )
    status = gold_stock_daily_qfq_factor_repair_status(
        context.instance,
        target_trade_date,
        upstream_batch_id=upstream_batch_id,
    )
    if not status.ready:
        return plan, status, "qfq_reconciliation_not_ready"
    if status.repair_required != plan.repair_required:
        return plan, status, "qfq_reconciliation_plan_mismatch"
    if plan.repair_required:
        return plan, status, "trend_repair_required"
    return plan, status, None


def _run_request(trade_date: str) -> dg.RunRequest:
    return build_run_request(
        run_key=build_asset_update_run_key(
            subject="gold_stock_daily_trend_channel_update",
            unit_id=f"{trade_date}:{FORMULA_VERSION}",
        ),
        partition_key=trade_date,
    )


def _summary_and_next_action(
    *,
    reason_code: str,
    target_trade_date: str | None,
) -> tuple[str, str]:
    target = target_trade_date or "当前窗口"
    messages = {
        "selected_for_update": (
            f"已触发：提交 {target} 的股票日线趋势通道更新。",
            "等待 paired result/state 和三个 blocking checks 完成。",
        ),
        "all_ready": (
            "未触发：最近窗口内的股票日线趋势通道均已 ready。",
            "等待新的交易日分区或新的 not-ready 分区。",
        ),
        "missing_registered_partition": (
            f"未触发：趋势通道分区存在内部缺口，首个缺失日期为 {target}。",
            "先补齐趋势通道 dynamic partition。",
        ),
        "pending_registered_partition_tail": (
            f"未触发：尾部日期 {target} 尚未注册。",
            "等待 06:00 分区注册 sensor 补齐。",
        ),
        "target_checks_failed": (
            f"未触发：{target} 已有目标文件但 Lake 审计失败。",
            "人工检查并修复坏分区；日常 sensor 不自动覆盖。",
        ),
        "qfq_not_ready": (
            f"未触发：{target} 的股票日线前复权尚未 ready。",
            "先完成同日 qfq materialization 和 blocking check。",
        ),
        "stock_basic_not_ready": (
            f"未触发：{target} 的股票基础信息 freshness 尚未 ready。",
            "先完成股票基础信息更新。",
        ),
        "stock_lifecycle_not_ready": (
            f"未触发：{target} 的股票生命周期 freshness 尚未 ready。",
            "先完成股票生命周期更新。",
        ),
        "previous_state_not_ready": (
            f"未触发：{target} 的前一交易日趋势状态未通过审计。",
            "先恢复前一 expected trade date 的 state。",
        ),
        "qfq_reconciliation_not_ready": (
            f"未触发：{target} 的 qfq 复权核对尚未绑定最新物化批次。",
            "等待同一 upstream batch 的 qfq reconciliation check。",
        ),
        "trend_repair_required": (
            f"未触发：{target} 的 qfq 历史发生重写，需要先修复趋势历史。",
            "等待 M5 趋势 repair completion；不得先计算当日状态。",
        ),
    }
    return messages.get(
        reason_code,
        (
            f"未触发：{target} 未满足股票日线趋势通道更新条件。",
            "查看 cursor 的 reason_code 和 gate_statuses。",
        ),
    )


def _cursor(
    *,
    evaluated_at: datetime,
    reason_code: str,
    target_trade_date: str | None,
    selected_trade_date: str | None,
    expected_window: ContinuityExpectedDateWindow,
    gap_status: ContinuityRegisteredGapStatus,
    batch_status: StockDailyTrendChannelBatchReadiness | None = None,
    gate_statuses: Mapping[str, Any] | None = None,
    repair_plan: GoldStockDailyQfqFactorRepairPlan | None = None,
    repair_status: GoldStockDailyQfqFactorRepairStatus | None = None,
) -> str:
    summary, next_action = _summary_and_next_action(
        reason_code=reason_code,
        target_trade_date=target_trade_date,
    )
    gates = compact_gate_statuses(
        {
            key: status
            for key, status in (gate_statuses or {}).items()
            if status is not None and not bool(getattr(status, "ready", False))
        }
    )
    if repair_plan is not None or repair_status is not None:
        gates["qfq_reconciliation"] = {
            "ready": bool(repair_status and repair_status.ready),
            "repair_required": bool(repair_plan and repair_plan.repair_required),
            "repair_required_code_count": (
                repair_plan.repair_required_code_count if repair_plan else 0
            ),
            "batch_matches": bool(repair_status and repair_status.ready),
        }
    details = build_cursor_details(
        sensor_name=GOLD_STOCK_DAILY_TREND_CHANNEL_SENSOR_NAME,
        job_name=GOLD_STOCK_DAILY_TREND_CHANNEL_JOB_NAME,
        asset_family="stock_daily_trend_channel",
        partition_set=cn_a_stock_daily_trend_channel_trade_days.name,
        reason_code=reason_code,
        blocked_component=("none" if selected_trade_date else reason_code),
        summary=summary,
        next_action=next_action,
        frontier=compact_continuity_frontier(
            gap_status,
            selected_trade_date=selected_trade_date,
        ),
        gate_statuses=gates,
        evidence={
            "target_readiness": compact_batch_frontier(
                batch_status,
                selected_trade_date=selected_trade_date,
            ),
            "formula_version": FORMULA_VERSION,
            "sql_count": getattr(batch_status, "sql_count", None),
            "slowest_query_ms": getattr(batch_status, "slowest_query_ms", None),
            "window_date_count": getattr(batch_status, "window_date_count", None),
        },
    )
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=(
            SensorCursorDecision.REQUEST_RUNS
            if selected_trade_date
            else SensorCursorDecision.SKIP
        ),
        target_date=target_trade_date,
        selected_count=1 if selected_trade_date else 0,
        blocked_count=(
            0
            if selected_trade_date or reason_code in {"all_ready", "no_expected_dates"}
            else 1
        ),
        sample_keys=(target_trade_date,) if target_trade_date else (),
        details=details,
    )


def _skip(
    *,
    context: dg.SensorEvaluationContext,
    evaluated_at: datetime,
    reason_code: str,
    target_trade_date: str | None,
    expected_window: ContinuityExpectedDateWindow,
    gap_status: ContinuityRegisteredGapStatus,
    batch_status: StockDailyTrendChannelBatchReadiness | None = None,
    gate_statuses: Mapping[str, Any] | None = None,
    repair_plan: GoldStockDailyQfqFactorRepairPlan | None = None,
    repair_status: GoldStockDailyQfqFactorRepairStatus | None = None,
) -> dg.SensorResult:
    del context
    summary, _ = _summary_and_next_action(
        reason_code=reason_code,
        target_trade_date=target_trade_date,
    )
    return dg.SensorResult(
        skip_reason=summary,
        cursor=_cursor(
            evaluated_at=evaluated_at,
            reason_code=reason_code,
            target_trade_date=target_trade_date,
            selected_trade_date=None,
            expected_window=expected_window,
            gap_status=gap_status,
            batch_status=batch_status,
            gate_statuses=gate_statuses,
            repair_plan=repair_plan,
            repair_status=repair_status,
        ),
    )


@dg.sensor(
    job=gold_stock_daily_trend_channel_update_job,
    name=GOLD_STOCK_DAILY_TREND_CHANNEL_SENSOR_NAME,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description=(
        "在 qfq、stock basic、lifecycle、前一状态和最新 qfq reconciliation "
        "全部 ready 后，按最早缺口触发股票日线趋势通道更新。"
    ),
)
def gold_stock_daily_trend_channel_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    expected_window = _load_expected_window(
        context,
        evaluated_at=evaluated_at,
    )
    registered_trade_dates = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_a_stock_daily_trend_channel_trade_days.name
            )
        )
    )
    gap_status = build_registered_gap_status(
        expected_trade_dates=expected_window.expected_trade_dates,
        registered_trade_dates=registered_trade_dates,
    )
    if not expected_window.expected_trade_dates:
        return _skip(
            context=context,
            evaluated_at=evaluated_at,
            reason_code="no_expected_dates",
            target_trade_date=None,
            expected_window=expected_window,
            gap_status=gap_status,
        )
    if gap_status.has_internal_gap:
        return _skip(
            context=context,
            evaluated_at=evaluated_at,
            reason_code="missing_registered_partition",
            target_trade_date=gap_status.first_internal_missing_date,
            expected_window=expected_window,
            gap_status=gap_status,
        )
    actionable_trade_dates = gap_status.actionable_expected_trade_dates
    if not actionable_trade_dates:
        return _skip(
            context=context,
            evaluated_at=evaluated_at,
            reason_code="pending_registered_partition_tail",
            target_trade_date=gap_status.first_trailing_unregistered_date,
            expected_window=expected_window,
            gap_status=gap_status,
        )

    first_previous_trade_date, batch_status = _load_target_readiness(
        context,
        actionable_trade_dates=actionable_trade_dates,
    )
    selection = select_first_not_ready_trade_date(
        expected_trade_dates=actionable_trade_dates,
        readiness=batch_status,
    )
    if selection.first_not_ready_trade_date is None:
        return _skip(
            context=context,
            evaluated_at=evaluated_at,
            reason_code="all_ready",
            target_trade_date=expected_window.max_trade_date,
            expected_window=expected_window,
            gap_status=gap_status,
            batch_status=batch_status,
        )
    target_trade_date = selection.first_not_ready_trade_date
    target_status = selection.selected_status
    if selection.selected_trade_date is None or (
        target_status is not None and target_status.materialized
    ):
        return _skip(
            context=context,
            evaluated_at=evaluated_at,
            reason_code="target_checks_failed",
            target_trade_date=target_trade_date,
            expected_window=expected_window,
            gap_status=gap_status,
            batch_status=batch_status,
            gate_statuses={"target": target_status},
        )

    qfq_status = partition_dataset_readiness_status_from_latest_checks(
        context.instance,
        GOLD_STOCK_DAILY_QFQ_READINESS_SPECS,
        partition_key=target_trade_date,
    )
    if not qfq_status.ready:
        return _skip(
            context=context,
            evaluated_at=evaluated_at,
            reason_code="qfq_not_ready",
            target_trade_date=target_trade_date,
            expected_window=expected_window,
            gap_status=gap_status,
            batch_status=batch_status,
            gate_statuses={"qfq": qfq_status},
        )
    basic_status = stock_basic_ready_for_trade_date(
        context.instance,
        target_trade_date,
    )
    if not basic_status.ready:
        return _skip(
            context=context,
            evaluated_at=evaluated_at,
            reason_code="stock_basic_not_ready",
            target_trade_date=target_trade_date,
            expected_window=expected_window,
            gap_status=gap_status,
            batch_status=batch_status,
            gate_statuses={"qfq": qfq_status, "stock_basic": basic_status},
        )
    lifecycle_status = silver_stock_lifecycle_ready_for_trade_date(
        context.instance,
        target_trade_date,
    )
    if not lifecycle_status.ready:
        return _skip(
            context=context,
            evaluated_at=evaluated_at,
            reason_code="stock_lifecycle_not_ready",
            target_trade_date=target_trade_date,
            expected_window=expected_window,
            gap_status=gap_status,
            batch_status=batch_status,
            gate_statuses={
                "qfq": qfq_status,
                "stock_basic": basic_status,
                "stock_lifecycle": lifecycle_status,
            },
        )

    target_index = actionable_trade_dates.index(target_trade_date)
    previous_trade_date = (
        first_previous_trade_date
        if target_index == 0
        else actionable_trade_dates[target_index - 1]
    )
    previous_state_status = _previous_state_status(
        context,
        target_trade_date=target_trade_date,
        previous_trade_date=previous_trade_date,
    )
    if previous_state_status is not None and not previous_state_status.ready:
        return _skip(
            context=context,
            evaluated_at=evaluated_at,
            reason_code="previous_state_not_ready",
            target_trade_date=target_trade_date,
            expected_window=expected_window,
            gap_status=gap_status,
            batch_status=batch_status,
            gate_statuses={"previous_state": previous_state_status},
        )

    repair_plan, repair_status, repair_reason = _qfq_reconciliation(
        context,
        target_trade_date=target_trade_date,
        previous_trade_date=previous_trade_date,
    )
    if repair_reason is not None:
        return _skip(
            context=context,
            evaluated_at=evaluated_at,
            reason_code=repair_reason,
            target_trade_date=target_trade_date,
            expected_window=expected_window,
            gap_status=gap_status,
            batch_status=batch_status,
            repair_plan=repair_plan,
            repair_status=repair_status,
        )

    cursor = _cursor(
        evaluated_at=evaluated_at,
        reason_code="selected_for_update",
        target_trade_date=target_trade_date,
        selected_trade_date=target_trade_date,
        expected_window=expected_window,
        gap_status=gap_status,
        batch_status=batch_status,
        gate_statuses={
            "qfq": qfq_status,
            "stock_basic": basic_status,
            "stock_lifecycle": lifecycle_status,
            "previous_state": previous_state_status,
        },
        repair_plan=repair_plan,
        repair_status=repair_status,
    )
    return dg.SensorResult(
        run_requests=[_run_request(target_trade_date)],
        cursor=cursor,
    )
