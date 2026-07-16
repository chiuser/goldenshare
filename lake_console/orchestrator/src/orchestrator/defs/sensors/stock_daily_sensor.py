from __future__ import annotations

from datetime import datetime
from typing import Any

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    DEFAULT_CONTINUITY_WINDOW_LIMIT,
    ContinuityExpectedDateWindow,
    ContinuityRegisteredGapStatus,
    build_continuity_cursor_details,
    build_registered_gap_status,
    load_expected_trade_date_window,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.configs import (
    build_stock_daily_raw_repair_run_config,
)
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
    load_sensor_cursor,
    sensor_cursor_details,
)
from orchestrator.defs.run_contracts.cursor_payloads import (
    build_cursor_details,
    compact_asset_readiness_status,
    compact_continuity_frontier,
    compact_dataset_readiness,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import (
    build_asset_update_run_key,
    build_repair_attempt_run_key,
)
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.readiness import (
    CN_A_SENSOR_TIMEZONE,
    RAW_STOCK_DAILY_ASSET_KEY,
    SILVER_STOCK_DAILY_ASSET_KEY,
    AssetReadinessStatus,
    DatasetReadinessStatus,
    materialized_partition_keys,
    raw_tushare_stock_daily_ready_for_trade_date,
    stock_basic_ready_for_trade_date,
    suspend_d_ready_for_trade_date,
)
from orchestrator.defs.sensors.cn_a_trade_day_sensor import STOCK_TRADE_DAY_MIN_DATE
from orchestrator.defs.sensors.stock_daily_raw_repair import (
    STOCK_DAILY_REPAIR_STATE_KEY,
    StockDailyMissingCodeRepairSelection,
    locate_stock_daily_missing_codes,
    select_stock_daily_missing_code_repair,
    stock_daily_repair_state_from_details,
)
from orchestrator.defs.sensors.stock_trade_day_sensor import (
    STOCK_TRADE_DAY_REGISTER_START,
)
from orchestrator.source_readiness.tushare.stock_daily import (
    StockDailySourceReadiness,
    check_stock_daily_source_readiness,
)


MAX_RUN_REQUESTS_PER_TICK = 2
RECENT_STOCK_DAILY_REPAIR_TRADE_DATE_LIMIT = 2


def _eligible_registered_trade_dates(
    context: dg.SensorEvaluationContext,
    evaluated_at: datetime,
) -> tuple[str, ...]:
    today = evaluated_at.date().isoformat()
    return tuple(
        key
        for key in sorted(
            context.instance.get_dynamic_partitions(cn_a_stock_trade_days.name)
        )
        if key <= today
    )


def _recent_registered_trade_dates(trade_dates: tuple[str, ...]) -> tuple[str, ...]:
    return trade_dates[-RECENT_STOCK_DAILY_REPAIR_TRADE_DATE_LIMIT:]


def _load_expected_stock_trade_day_window(
    context: dg.SensorEvaluationContext,
    evaluated_at: datetime,
) -> ContinuityExpectedDateWindow:
    lake_root = context.resources.lake_root
    duckdb_resource = context.resources.duckdb
    lake_root.ensure_available_for_run()
    calendar_path = silver_trade_calendar_path(lake_root.root())
    if not calendar_path.exists():
        raise FileNotFoundError(f"silver_trade_calendar file is missing: {calendar_path}")

    with duckdb_resource.connect() as connection:
        return load_expected_trade_date_window(
            connection,
            calendar_path,
            evaluated_at=evaluated_at,
            min_trade_date=STOCK_TRADE_DAY_MIN_DATE,
            same_day_register_start=STOCK_TRADE_DAY_REGISTER_START,
            window_limit=DEFAULT_CONTINUITY_WINDOW_LIMIT,
        )


def _stock_trade_day_registered_gap(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime,
    registered_keys: tuple[str, ...],
) -> tuple[ContinuityExpectedDateWindow, ContinuityRegisteredGapStatus]:
    expected_window = _load_expected_stock_trade_day_window(context, evaluated_at)
    gap_status = build_registered_gap_status(
        expected_trade_dates=expected_window.expected_trade_dates,
        registered_trade_dates=registered_keys,
    )
    return expected_window, gap_status


def _continuity_details(
    *,
    expected_window: ContinuityExpectedDateWindow,
    gap_status: ContinuityRegisteredGapStatus,
) -> dict[str, object]:
    return build_continuity_cursor_details(
        expected_window=expected_window,
        gap_status=gap_status,
        batch_readiness=None,
        selection=None,
    )


def _registered_gap_skip_reason(
    *,
    layer_label: str,
    gap_status: ContinuityRegisteredGapStatus,
) -> str:
    return (
        "股票交易日分区存在内部缺口，最早内部缺失日期为 "
        f"{gap_status.first_internal_missing_date}，暂不触发股票日线 "
        f"{layer_label} 更新。"
    )


def _compact_dataset_status(
    status: DatasetReadinessStatus,
) -> dict[str, object]:
    return compact_dataset_readiness(status) or {}


def _compact_asset_status(status: AssetReadinessStatus) -> dict[str, object]:
    return compact_asset_readiness_status(status) or {}


def _source_readiness_payload(
    source_readiness: StockDailySourceReadiness,
) -> dict[str, object]:
    return {
        "is_ready": source_readiness.is_ready,
        "trade_date": source_readiness.trade_date,
        "row_count": source_readiness.row_count,
        "checked_at": source_readiness.checked_at,
        "reason": source_readiness.reason,
    }


def _supporting_facts_ready(
    *,
    context: dg.SensorEvaluationContext,
    trade_date: str,
    gate_statuses_by_trade_date: dict[str, dict[str, object]],
) -> bool:
    gate_statuses_by_trade_date.setdefault(trade_date, {})
    basic_status = stock_basic_ready_for_trade_date(context.instance, trade_date)
    gate_statuses_by_trade_date[trade_date]["stock_basic"] = _compact_dataset_status(
        basic_status
    )
    if not basic_status.ready:
        return False

    suspend_status = suspend_d_ready_for_trade_date(context.instance, trade_date)
    gate_statuses_by_trade_date[trade_date]["suspend_d"] = _compact_dataset_status(
        suspend_status
    )
    return suspend_status.ready


def _stock_daily_source_ready(
    *,
    context: dg.SensorEvaluationContext,
    trade_date: str,
    evaluated_at: datetime,
    gate_statuses_by_trade_date: dict[str, dict[str, object]],
) -> bool:
    source_readiness = check_stock_daily_source_readiness(
        tushare=context.resources.tushare,
        trade_date=trade_date,
        checked_at=evaluated_at,
    )
    gate_statuses_by_trade_date.setdefault(trade_date, {})
    gate_statuses_by_trade_date[trade_date]["source_readiness"] = (
        _source_readiness_payload(source_readiness)
    )
    return source_readiness.is_ready


def _clear_repair_state_for_trade_date(
    repair_state: dict[str, Any],
    trade_date: str,
) -> None:
    dates = repair_state.setdefault("dates", {})
    if isinstance(dates, dict):
        dates.pop(trade_date, None)


def _repair_selection_payload(
    selection: StockDailyMissingCodeRepairSelection,
) -> dict[str, object]:
    return {
        "trade_date": selection.trade_date,
        "should_submit": selection.should_submit,
        "reason": selection.reason,
        "missing_codes_hash": selection.missing_codes_hash,
        "repair_attempt": selection.repair_attempt,
        "next_retry_at": (
            selection.next_retry_at.isoformat() if selection.next_retry_at else None
        ),
        "manual_required": selection.manual_required,
        "waiting": selection.waiting,
        "exhausted": selection.exhausted,
    }


def _status_payload_ready(status_payload: object) -> bool:
    if not isinstance(status_payload, dict):
        return True
    if "ready" in status_payload:
        return bool(status_payload["ready"])
    if "is_ready" in status_payload:
        return bool(status_payload["is_ready"])
    return True


def _blocked_component_from_gate_statuses(
    *,
    trade_date: str | None,
    gate_statuses_by_trade_date: dict[str, dict[str, object]],
    default: str,
) -> str:
    if trade_date is None:
        return default
    statuses = gate_statuses_by_trade_date.get(trade_date, {})
    for status_key, component in (
        ("stock_basic", "stock_basic"),
        ("suspend_d", "suspend_d"),
        ("raw_tushare_stock_daily", "raw_tushare_stock_daily"),
        ("source_readiness", "tushare_daily_source"),
    ):
        if status_key in statuses and not _status_payload_ready(statuses[status_key]):
            return component
    return default


def _blocked_component_from_repair(
    *,
    trade_date: str | None,
    repair_details: dict[str, object],
) -> str | None:
    if trade_date is None:
        return None
    detail = repair_details.get(trade_date)
    if not isinstance(detail, dict):
        return None
    selection = detail.get("selection")
    if not isinstance(selection, dict):
        return None
    if selection.get("manual_required") or selection.get("waiting") or selection.get(
        "exhausted"
    ):
        return "raw_tushare_stock_daily_repair"
    return None


def _first_blocked_reason_code(
    *,
    trade_date: str | None,
    component: str,
    gate_statuses_by_trade_date: dict[str, dict[str, object]],
) -> str | None:
    if trade_date is None:
        return None
    component_to_status_key = {
        "stock_basic": "stock_basic",
        "suspend_d": "suspend_d",
        "raw_tushare_stock_daily": "raw_tushare_stock_daily",
        "tushare_daily_source": "source_readiness",
    }
    status_key = component_to_status_key.get(component)
    status_payload = gate_statuses_by_trade_date.get(trade_date, {}).get(status_key)
    if isinstance(status_payload, dict):
        reason_code = status_payload.get("reason_code") or status_payload.get("reason")
        return str(reason_code) if reason_code is not None else None
    return None


def _repair_cursor_summary(
    repair_details: dict[str, object],
) -> dict[str, object]:
    if not repair_details:
        return {
            "repair_trade_date_count": 0,
            "first_repair_trade_date": None,
            "first_repair_reason_code": None,
            "first_repair_missing_count": 0,
            "first_repair_attempt": None,
        }
    first_trade_date = sorted(repair_details)[0]
    detail = repair_details.get(first_trade_date)
    locator = detail.get("locator") if isinstance(detail, dict) else {}
    selection = detail.get("selection") if isinstance(detail, dict) else {}
    if not isinstance(locator, dict):
        locator = {}
    if not isinstance(selection, dict):
        selection = {}
    return {
        "repair_trade_date_count": len(repair_details),
        "first_repair_trade_date": first_trade_date,
        "first_repair_reason_code": selection.get("reason"),
        "first_repair_missing_count": locator.get("missing_count", 0),
        "first_repair_attempt": selection.get("repair_attempt"),
    }


def _raw_cursor_summary_and_next_action(
    *,
    selected_full_day_count: int,
    selected_repair_count: int,
    blocked_component: str,
    target_date: str | None,
    raw_missing_count: int,
) -> tuple[str, str]:
    selected_count = selected_full_day_count + selected_repair_count
    if selected_count:
        if selected_full_day_count and selected_repair_count:
            summary = (
                "已触发：提交 "
                f"{selected_count} 个股票日线 raw 更新，其中 "
                f"{selected_full_day_count} 个全量分区、"
                f"{selected_repair_count} 个 missing-code repair。"
            )
        elif selected_repair_count:
            summary = (
                f"已触发：提交 {selected_repair_count} 个股票日线 raw "
                "missing-code repair。"
            )
        else:
            summary = (
                f"已触发：提交 {selected_full_day_count} 个股票日线 raw 全量更新。"
            )
        return summary, "等待本次 raw run 完成，然后查看 raw blocking checks。"
    if blocked_component == "cn_a_stock_trade_days":
        return (
            f"未触发：股票交易日分区存在缺口，目标停在 {target_date}。",
            "先补齐 cn_a_stock_trade_days 动态分区，再等待下一次 tick。",
        )
    if blocked_component == "stock_basic":
        return (
            f"未触发：股票日线 raw 在 {target_date} 被 stock_basic 阻断。",
            "先完成 stock_basic raw/silver freshness 与 blocking checks，再等待下一次 tick。",
        )
    if blocked_component == "suspend_d":
        return (
            f"未触发：股票日线 raw 在 {target_date} 被 suspend_d 阻断。",
            "先完成同日停复牌 raw/silver 更新与 blocking checks，再等待下一次 tick。",
        )
    if blocked_component == "tushare_daily_source":
        return (
            f"未触发：股票日线 raw 在 {target_date} 等待 Tushare daily 源站数据。",
            "等待源站返回当日股票日线后，下一次 tick 会重新探测。",
        )
    if blocked_component == "raw_tushare_stock_daily_repair":
        return (
            f"未触发：股票日线 raw repair 在 {target_date} 等待重试或人工处理。",
            "查看 repair 摘要和 raw checks，确认是否等待 backoff、补源站数据或人工处理。",
        )
    if raw_missing_count:
        return (
            "未触发：股票日线 raw 仍有缺失分区，但本 tick 没有可提交项。",
            "查看首个缺失/阻断日期的上游 ready 状态，修复后等待下一次 tick。",
        )
    return (
        "未触发：股票日线 raw 当前全部就绪。",
        "无需处理；等待新交易日分区或后续 repair 机会。",
    )


def _silver_cursor_summary_and_next_action(
    *,
    selected_count: int,
    blocked_component: str,
    target_date: str | None,
    pending_count: int,
) -> tuple[str, str]:
    if selected_count:
        return (
            f"已触发：提交 {selected_count} 个股票日线 silver 更新。",
            "等待本次 silver run 完成，然后查看 silver blocking checks。",
        )
    if blocked_component == "cn_a_stock_trade_days":
        return (
            f"未触发：股票交易日分区存在缺口，目标停在 {target_date}。",
            "先补齐 cn_a_stock_trade_days 动态分区，再等待下一次 tick。",
        )
    if blocked_component == "stock_basic":
        return (
            f"未触发：股票日线 silver 在 {target_date} 被 stock_basic 阻断。",
            "先完成 stock_basic raw/silver freshness 与 blocking checks，再等待下一次 tick。",
        )
    if blocked_component == "suspend_d":
        return (
            f"未触发：股票日线 silver 在 {target_date} 被 suspend_d 阻断。",
            "先完成同日停复牌 raw/silver 更新与 blocking checks，再等待下一次 tick。",
        )
    if blocked_component == "raw_tushare_stock_daily":
        return (
            f"未触发：股票日线 silver 在 {target_date} 等待 raw_tushare_stock_daily。",
            "先让同日 raw materialization 和 raw blocking checks 全部通过，再等待下一次 tick。",
        )
    if pending_count:
        return (
            "未触发：股票日线 silver 仍有缺失分区，但本 tick 没有可提交项。",
            "查看首个待补日期的 raw 和基础事实 ready 状态，修复后等待下一次 tick。",
        )
    return (
        "未触发：股票日线 silver 当前全部就绪。",
        "无需处理；等待新交易日分区。",
    )


def _raw_sensor_cursor(
    *,
    evaluated_at: datetime,
    registered_count: int,
    raw_missing_keys: tuple[str, ...],
    selected_full_day_keys: tuple[str, ...],
    selected_repair_keys: tuple[str, ...],
    blocked_keys: tuple[str, ...],
    gate_statuses_by_trade_date: dict[str, dict[str, object]],
    repair_state: dict[str, Any],
    repair_details: dict[str, object],
    continuity_details: dict[str, object] | None,
) -> str:
    selected_keys = (*selected_full_day_keys, *selected_repair_keys)
    decision = (
        SensorCursorDecision.REQUEST_RUNS
        if selected_keys
        else SensorCursorDecision.SKIP
    )
    target_date = (
        selected_keys[0]
        if selected_keys
        else blocked_keys[0]
        if blocked_keys
        else raw_missing_keys[0]
        if raw_missing_keys
        else None
    )
    reason_code = "request_run" if selected_keys else "all_ready"
    blocked_component = "none"
    if not selected_keys:
        if blocked_keys:
            reason_code = "blocked"
            blocked_component = (
                _blocked_component_from_repair(
                    trade_date=target_date,
                    repair_details=repair_details,
                )
                or _blocked_component_from_gate_statuses(
                    trade_date=target_date,
                    gate_statuses_by_trade_date=gate_statuses_by_trade_date,
                    default=(
                        "cn_a_stock_trade_days"
                        if not gate_statuses_by_trade_date
                        else "raw_tushare_stock_daily_repair"
                    ),
                )
            )
        elif raw_missing_keys:
            reason_code = "pending_raw"
            blocked_component = "raw_tushare_stock_daily"
    summary, next_action = _raw_cursor_summary_and_next_action(
        selected_full_day_count=len(selected_full_day_keys),
        selected_repair_count=len(selected_repair_keys),
        blocked_component=blocked_component,
        target_date=target_date,
        raw_missing_count=len(raw_missing_keys),
    )
    repair_summary = _repair_cursor_summary(repair_details)
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_date,
        selected_count=len(selected_keys),
        blocked_count=len(blocked_keys),
        sample_keys=selected_keys or blocked_keys or raw_missing_keys,
        details=build_cursor_details(
            sensor_name="raw_stock_daily_update_job_sensor",
            job_name="raw_stock_daily_update_job",
            asset_family="stock_daily",
            partition_set=cn_a_stock_trade_days.name,
            reason_code=reason_code,
            blocked_component=blocked_component,
            summary=summary,
            next_action=next_action,
            frontier=compact_continuity_frontier(
                continuity_details,
                selected_trade_date=target_date,
            ),
            evidence={
                "registered_count": registered_count,
                "raw_missing_count": len(raw_missing_keys),
                "raw_missing_sample_keys": list(raw_missing_keys[:3]),
                "selected_full_day_count": len(selected_full_day_keys),
                "selected_repair_count": len(selected_repair_keys),
                "blocked_count": len(blocked_keys),
                "first_blocked_key": blocked_keys[0] if blocked_keys else None,
                "first_blocked_component": (
                    blocked_component if blocked_component != "none" else None
                ),
                "first_blocked_reason_code": _first_blocked_reason_code(
                    trade_date=blocked_keys[0] if blocked_keys else None,
                    component=blocked_component,
                    gate_statuses_by_trade_date=gate_statuses_by_trade_date,
                ),
                "gate_trade_date_count": len(gate_statuses_by_trade_date),
                **repair_summary,
                "max_run_requests_per_tick": MAX_RUN_REQUESTS_PER_TICK,
                "recent_repair_trade_date_limit": RECENT_STOCK_DAILY_REPAIR_TRADE_DATE_LIMIT,
            },
            runtime_state={STOCK_DAILY_REPAIR_STATE_KEY: repair_state},
        ),
    )


def _silver_sensor_cursor(
    *,
    evaluated_at: datetime,
    registered_count: int,
    pending_keys: tuple[str, ...],
    selected_keys: tuple[str, ...],
    blocked_keys: tuple[str, ...],
    gate_statuses_by_trade_date: dict[str, dict[str, object]],
    continuity_details: dict[str, object] | None,
) -> str:
    decision = (
        SensorCursorDecision.REQUEST_RUNS
        if selected_keys
        else SensorCursorDecision.SKIP
    )
    target_date = (
        selected_keys[0]
        if selected_keys
        else blocked_keys[0]
        if blocked_keys
        else pending_keys[0]
        if pending_keys
        else None
    )
    reason_code = "request_run" if selected_keys else "all_ready"
    blocked_component = "none"
    if not selected_keys:
        if blocked_keys:
            reason_code = "blocked"
            blocked_component = _blocked_component_from_gate_statuses(
                trade_date=target_date,
                gate_statuses_by_trade_date=gate_statuses_by_trade_date,
                default=(
                    "cn_a_stock_trade_days"
                    if not gate_statuses_by_trade_date
                    else "raw_tushare_stock_daily"
                ),
            )
        elif pending_keys:
            reason_code = "pending_silver"
            blocked_component = "silver_stock_daily"
    summary, next_action = _silver_cursor_summary_and_next_action(
        selected_count=len(selected_keys),
        blocked_component=blocked_component,
        target_date=target_date,
        pending_count=len(pending_keys),
    )
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_date,
        selected_count=len(selected_keys),
        blocked_count=len(blocked_keys),
        sample_keys=selected_keys or blocked_keys or pending_keys,
        details=build_cursor_details(
            sensor_name="silver_stock_daily_update_job_sensor",
            job_name="silver_stock_daily_update_job",
            asset_family="stock_daily",
            partition_set=cn_a_stock_trade_days.name,
            reason_code=reason_code,
            blocked_component=blocked_component,
            summary=summary,
            next_action=next_action,
            frontier=compact_continuity_frontier(
                continuity_details,
                selected_trade_date=target_date,
            ),
            evidence={
                "registered_count": registered_count,
                "pending_count": len(pending_keys),
                "selected_count": len(selected_keys),
                "blocked_count": len(blocked_keys),
                "first_blocked_key": blocked_keys[0] if blocked_keys else None,
                "first_blocked_component": (
                    blocked_component if blocked_component != "none" else None
                ),
                "first_blocked_reason_code": _first_blocked_reason_code(
                    trade_date=blocked_keys[0] if blocked_keys else None,
                    component=blocked_component,
                    gate_statuses_by_trade_date=gate_statuses_by_trade_date,
                ),
                "gate_trade_date_count": len(gate_statuses_by_trade_date),
                "max_run_requests_per_tick": MAX_RUN_REQUESTS_PER_TICK,
            },
        ),
    )


@dg.sensor(
    job_name="raw_stock_daily_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"duckdb", "lake_root", "tushare"},
    description="股票基础信息、停复牌和源站日线就绪后，触发股票日线 raw 更新或受控 missing-code repair。",
)
def raw_stock_daily_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    registered_keys = _eligible_registered_trade_dates(context, evaluated_at)
    expected_window, gap_status = _stock_trade_day_registered_gap(
        context,
        evaluated_at=evaluated_at,
        registered_keys=registered_keys,
    )
    continuity_details = _continuity_details(
        expected_window=expected_window,
        gap_status=gap_status,
    )
    if gap_status.has_internal_gap:
        repair_state = stock_daily_repair_state_from_details(
            sensor_cursor_details(load_sensor_cursor(context.cursor))
        )
        cursor = _raw_sensor_cursor(
            evaluated_at=evaluated_at,
            registered_count=len(registered_keys),
            raw_missing_keys=(),
            selected_full_day_keys=(),
            selected_repair_keys=(),
            blocked_keys=(gap_status.first_internal_missing_date,),
            gate_statuses_by_trade_date={},
            repair_state=repair_state,
            repair_details={},
            continuity_details=continuity_details,
        )
        return dg.SensorResult(
            skip_reason=_registered_gap_skip_reason(
                layer_label="raw",
                gap_status=gap_status,
            ),
            cursor=cursor,
        )

    raw_materialized_keys = materialized_partition_keys(
        context.instance,
        (RAW_STOCK_DAILY_ASSET_KEY,),
    )
    raw_missing_keys = tuple(
        key for key in registered_keys if key not in raw_materialized_keys
    )
    selected_full_day_keys: list[str] = []
    selected_repair_keys: list[str] = []
    selected_repair_run_inputs: dict[str, tuple[tuple[str, ...], str, int]] = {}
    blocked_keys: list[str] = []
    gate_statuses_by_trade_date: dict[str, dict[str, object]] = {}
    repair_details: dict[str, object] = {}
    cursor_payload = load_sensor_cursor(context.cursor)
    previous_cursor_details = sensor_cursor_details(cursor_payload)
    repair_state = stock_daily_repair_state_from_details(previous_cursor_details)

    for trade_date in raw_missing_keys[:MAX_RUN_REQUESTS_PER_TICK]:
        if len(selected_full_day_keys) >= MAX_RUN_REQUESTS_PER_TICK:
            break
        if not _supporting_facts_ready(
            context=context,
            trade_date=trade_date,
            gate_statuses_by_trade_date=gate_statuses_by_trade_date,
        ):
            blocked_keys.append(trade_date)
            continue
        if not _stock_daily_source_ready(
            context=context,
            trade_date=trade_date,
            evaluated_at=evaluated_at,
            gate_statuses_by_trade_date=gate_statuses_by_trade_date,
        ):
            blocked_keys.append(trade_date)
            continue
        selected_full_day_keys.append(trade_date)

    remaining_capacity = MAX_RUN_REQUESTS_PER_TICK - len(selected_full_day_keys)
    recent_trade_dates = _recent_registered_trade_dates(registered_keys)
    for trade_date in recent_trade_dates:
        if remaining_capacity <= 0:
            break
        if trade_date in selected_full_day_keys or trade_date not in raw_materialized_keys:
            continue
        raw_status = raw_tushare_stock_daily_ready_for_trade_date(
            context.instance,
            trade_date,
        )
        gate_statuses_by_trade_date.setdefault(trade_date, {})
        gate_statuses_by_trade_date[trade_date]["raw_tushare_stock_daily"] = (
            _compact_asset_status(raw_status)
        )
        if raw_status.ready:
            _clear_repair_state_for_trade_date(repair_state, trade_date)
            continue
        if not _supporting_facts_ready(
            context=context,
            trade_date=trade_date,
            gate_statuses_by_trade_date=gate_statuses_by_trade_date,
        ):
            blocked_keys.append(trade_date)
            continue
        if not _stock_daily_source_ready(
            context=context,
            trade_date=trade_date,
            evaluated_at=evaluated_at,
            gate_statuses_by_trade_date=gate_statuses_by_trade_date,
        ):
            blocked_keys.append(trade_date)
            continue

        locator = locate_stock_daily_missing_codes(
            lake_root_path=context.resources.lake_root.root(),
            duckdb=context.resources.duckdb,
            trade_date=trade_date,
        )
        selection = select_stock_daily_missing_code_repair(
            locator=locator,
            evaluated_at=evaluated_at,
            repair_state=repair_state,
        )
        repair_state = selection.repair_state
        repair_details[trade_date] = {
            "locator": {
                "raw_file_exists": locator.raw_file_exists,
                "expected_count": locator.expected_count,
                "raw_code_count": locator.raw_code_count,
                "missing_count": locator.missing_count,
                "missing_sample_codes": list(locator.missing_sample_codes),
                "extra_count": locator.extra_count,
                "duplicate_key_count": locator.duplicate_key_count,
                "conflict_key_count": locator.conflict_key_count,
                "extra_sample_codes": list(locator.extra_sample_codes),
                "duplicate_sample_codes": list(locator.duplicate_sample_codes),
                "conflict_sample_codes": list(locator.conflict_sample_codes),
                "scan_error_code": locator.scan_error_code,
                "scan_error": locator.scan_error,
            },
            "selection": _repair_selection_payload(selection),
        }
        if not selection.should_submit:
            if selection.manual_required or selection.waiting:
                blocked_keys.append(trade_date)
            continue

        selected_repair_keys.append(trade_date)
        selected_repair_run_inputs[trade_date] = (
            locator.missing_codes,
            str(selection.missing_codes_hash),
            selection.repair_attempt,
        )
        remaining_capacity -= 1

    selected_full_day_tuple = tuple(selected_full_day_keys)
    selected_repair_tuple = tuple(selected_repair_keys)
    cursor = _raw_sensor_cursor(
        evaluated_at=evaluated_at,
        registered_count=len(registered_keys),
        raw_missing_keys=raw_missing_keys,
        selected_full_day_keys=selected_full_day_tuple,
        selected_repair_keys=selected_repair_tuple,
        blocked_keys=tuple(blocked_keys),
        gate_statuses_by_trade_date=gate_statuses_by_trade_date,
        repair_state=repair_state,
        repair_details=repair_details,
        continuity_details=continuity_details,
    )

    run_requests = [
        build_run_request(
            partition_key=trade_date,
            run_key=build_asset_update_run_key(
                subject="raw_stock_daily_update",
                unit_id=trade_date,
            ),
        )
        for trade_date in selected_full_day_tuple
    ]
    for trade_date in selected_repair_tuple:
        missing_codes, missing_hash, repair_attempt = selected_repair_run_inputs[
            trade_date
        ]
        run_requests.append(
            build_run_request(
                partition_key=trade_date,
                run_key=build_repair_attempt_run_key(
                    subject="raw_stock_daily_update",
                    repair_scope_id=(
                        f"{trade_date}:missing_code_repair:{missing_hash}"
                    ),
                    attempt=repair_attempt,
                ),
                run_config=build_stock_daily_raw_repair_run_config(
                    ts_codes=missing_codes,
                    missing_codes_hash=missing_hash,
                    repair_attempt=repair_attempt,
                ),
            )
        )

    if not run_requests:
        if not registered_keys:
            skip_reason = "当前没有已注册股票交易日分区。"
        elif raw_missing_keys:
            skip_reason = "股票日线 raw 缺失，但基础事实或 Tushare 源站门禁未满足。"
        elif repair_details:
            skip_reason = "股票日线 raw 已生成但 repair 门禁未满足或需要人工处理。"
        else:
            skip_reason = "当前股票日线 raw 已就绪，没有需要提交的 raw run。"
        return dg.SensorResult(skip_reason=skip_reason, cursor=cursor)

    return dg.SensorResult(run_requests=run_requests, cursor=cursor)


@dg.sensor(
    job_name="silver_stock_daily_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"duckdb", "lake_root"},
    description="股票日线 raw 与基础事实 ready 后，触发股票日线 silver-only 更新。",
)
def silver_stock_daily_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    registered_keys = _eligible_registered_trade_dates(context, evaluated_at)
    expected_window, gap_status = _stock_trade_day_registered_gap(
        context,
        evaluated_at=evaluated_at,
        registered_keys=registered_keys,
    )
    continuity_details = _continuity_details(
        expected_window=expected_window,
        gap_status=gap_status,
    )
    if gap_status.has_internal_gap:
        cursor = _silver_sensor_cursor(
            evaluated_at=evaluated_at,
            registered_count=len(registered_keys),
            pending_keys=(),
            selected_keys=(),
            blocked_keys=(gap_status.first_internal_missing_date,),
            gate_statuses_by_trade_date={},
            continuity_details=continuity_details,
        )
        return dg.SensorResult(
            skip_reason=_registered_gap_skip_reason(
                layer_label="silver",
                gap_status=gap_status,
            ),
            cursor=cursor,
        )

    silver_materialized_keys = materialized_partition_keys(
        context.instance,
        (SILVER_STOCK_DAILY_ASSET_KEY,),
    )
    pending_keys = tuple(
        key for key in registered_keys if key not in silver_materialized_keys
    )
    candidate_keys = pending_keys[:MAX_RUN_REQUESTS_PER_TICK]
    selected_keys: list[str] = []
    blocked_keys: list[str] = []
    gate_statuses_by_trade_date: dict[str, dict[str, object]] = {}

    for trade_date in candidate_keys:
        if not _supporting_facts_ready(
            context=context,
            trade_date=trade_date,
            gate_statuses_by_trade_date=gate_statuses_by_trade_date,
        ):
            blocked_keys.append(trade_date)
            continue

        raw_status = raw_tushare_stock_daily_ready_for_trade_date(
            context.instance,
            trade_date,
        )
        gate_statuses_by_trade_date.setdefault(trade_date, {})
        gate_statuses_by_trade_date[trade_date]["raw_tushare_stock_daily"] = (
            _compact_asset_status(raw_status)
        )
        if not raw_status.ready:
            blocked_keys.append(trade_date)
            continue

        selected_keys.append(trade_date)

    selected_tuple = tuple(selected_keys)
    cursor = _silver_sensor_cursor(
        evaluated_at=evaluated_at,
        registered_count=len(registered_keys),
        pending_keys=pending_keys,
        selected_keys=selected_tuple,
        blocked_keys=tuple(blocked_keys),
        gate_statuses_by_trade_date=gate_statuses_by_trade_date,
        continuity_details=continuity_details,
    )

    if not selected_tuple:
        if not pending_keys:
            skip_reason = "当前所有已注册交易日的股票日线 silver 分区都已经生成完成。"
        elif blocked_keys:
            skip_reason = "股票日线 silver 前置 raw 或基础事实 readiness 门禁未满足。"
        else:
            skip_reason = "当前没有满足门禁的股票日线 silver 待补分区。"
        return dg.SensorResult(skip_reason=skip_reason, cursor=cursor)

    return dg.SensorResult(
        run_requests=[
            build_run_request(
                partition_key=trade_date,
                run_key=build_asset_update_run_key(
                    subject="silver_stock_daily_update",
                    unit_id=trade_date,
                ),
            )
            for trade_date in selected_tuple
        ],
        cursor=cursor,
    )
