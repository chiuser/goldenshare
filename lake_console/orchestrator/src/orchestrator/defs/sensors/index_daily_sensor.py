from datetime import datetime, time
from typing import Any

import dagster as dg

from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.paths import silver_index_basic_path
from orchestrator.defs.run_contracts.configs import build_index_daily_update_job_run_config
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
    load_sensor_cursor,
    sensor_cursor_details,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.index_daily_late_arrival_repair import (
    MAX_REPAIR_ATTEMPTS_PER_CODE_PER_DAY,
    MAX_REPAIR_CURSOR_CODE_COUNT,
    MAX_REPAIR_RUN_REQUESTS_PER_TICK,
    select_index_daily_pending_code_runs,
)
from orchestrator.defs.sensors.index_daily_raw_file_readiness import (
    MAX_RAW_GAP_SAMPLE_COUNT,
    RAW_GAP_AUDIT_TRADE_DAY_LIMIT,
    audit_index_daily_raw_gaps,
    check_index_daily_raw_files_for_trade_date,
)
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE
from orchestrator.source_readiness.tushare.index_daily import (
    check_index_daily_source_readiness,
)


INDEX_DAILY_SOURCE_PROBE_START = time(16, 0)
MAX_RUN_REQUESTS_PER_TICK = 500


def _runnable_trade_dates(
    registered_trade_days: tuple[str, ...],
    evaluated_at: datetime,
) -> tuple[str, ...]:
    today = evaluated_at.date().isoformat()
    probe_window_started = evaluated_at.time() >= INDEX_DAILY_SOURCE_PROBE_START
    return tuple(
        trade_date
        for trade_date in registered_trade_days
        if trade_date < today or (trade_date == today and probe_window_started)
    )


def _recent_trade_dates(
    trade_dates: tuple[str, ...],
    *,
    limit: int = RAW_GAP_AUDIT_TRADE_DAY_LIMIT,
) -> tuple[str, ...]:
    if limit <= 0:
        raise ValueError("limit must be positive.")
    return trade_dates[-limit:]


def _select_pending_codes(
    *,
    cursor_payload: dict[str, Any],
    target_trade_date: str,
    pending_codes: tuple[str, ...],
) -> tuple[tuple[str, ...], int]:
    if not pending_codes:
        return (), 0

    cursor_trade_date = cursor_payload.get("target_date")
    raw_offset = sensor_cursor_details(cursor_payload).get("next_pending_offset", 0)
    start_offset = raw_offset if cursor_trade_date == target_trade_date else 0
    if not isinstance(start_offset, int) or start_offset < 0:
        start_offset = 0
    start_offset = start_offset % len(pending_codes)

    rotated_pending_codes = pending_codes[start_offset:] + pending_codes[:start_offset]
    selected_codes = rotated_pending_codes[:MAX_RUN_REQUESTS_PER_TICK]
    next_offset = (start_offset + len(selected_codes)) % len(pending_codes)
    return selected_codes, next_offset


def _cursor_payload(
    *,
    evaluated_at: datetime,
    today: str,
    registered_trade_day_count: int,
    registered_code_count: int,
    target_trade_date: str | None,
    source_ready: bool | None,
    source_row_count: int | None,
    pending_count: int,
    selected_codes: tuple[str, ...],
    next_pending_offset: int,
    audit_trade_date_count: int | None = None,
    audit_expected_pair_count: int | None = None,
    audit_ready_pair_count: int | None = None,
    audit_missing_pair_count: int | None = None,
    audit_missing_file_count: int | None = None,
    audit_missing_trade_date_pair_count: int | None = None,
    audit_no_raw_history_count: int | None = None,
    audit_no_raw_history_samples: tuple[str, ...] = (),
    raw_scan_error_code: str | None = None,
    raw_scan_error: str | None = None,
    repair_state: dict[str, Any] | None = None,
    repair_new_code_count: int | None = None,
    repair_due_count: int | None = None,
    repair_selected_count: int | None = None,
    repair_waiting_count: int | None = None,
    repair_exhausted_count: int | None = None,
    repair_budget_limited_count: int | None = None,
    repair_state_code_count: int | None = None,
    repair_cursor_code_limit_exceeded: bool | None = None,
) -> str:
    decision = (
        SensorCursorDecision.REQUEST_RUNS
        if selected_codes
        else SensorCursorDecision.SKIP
    )
    details = {
        "today": today,
        "registered_trade_day_count": registered_trade_day_count,
        "registered_code_count": registered_code_count,
        "source_ready": source_ready,
        "source_row_count": source_row_count,
        "pending_count": pending_count,
        "selected_codes": list(selected_codes),
        "next_pending_offset": next_pending_offset,
        "max_run_requests_per_tick": MAX_RUN_REQUESTS_PER_TICK,
        "max_repair_run_requests_per_tick": MAX_REPAIR_RUN_REQUESTS_PER_TICK,
        "max_repair_attempts_per_code_per_day": (
            MAX_REPAIR_ATTEMPTS_PER_CODE_PER_DAY
        ),
        "max_repair_cursor_code_count": MAX_REPAIR_CURSOR_CODE_COUNT,
        "audit_trade_date_count": audit_trade_date_count,
        "audit_expected_pair_count": audit_expected_pair_count,
        "audit_ready_pair_count": audit_ready_pair_count,
        "audit_missing_pair_count": audit_missing_pair_count,
        "audit_missing_file_count": audit_missing_file_count,
        "audit_missing_trade_date_pair_count": audit_missing_trade_date_pair_count,
        "audit_no_raw_history_count": audit_no_raw_history_count,
        "audit_no_raw_history_samples": list(audit_no_raw_history_samples),
        "raw_scan_error_code": raw_scan_error_code,
        "raw_scan_error": raw_scan_error,
        "repair_new_code_count": repair_new_code_count,
        "repair_due_count": repair_due_count,
        "repair_selected_count": repair_selected_count,
        "repair_waiting_count": repair_waiting_count,
        "repair_exhausted_count": repair_exhausted_count,
        "repair_budget_limited_count": repair_budget_limited_count,
        "repair_state_code_count": repair_state_code_count,
        "repair_cursor_code_limit_exceeded": repair_cursor_code_limit_exceeded,
    }
    if repair_state:
        details["repair_state"] = repair_state

    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_trade_date,
        selected_count=len(selected_codes),
        blocked_count=max(0, pending_count - len(selected_codes)),
        sample_keys=selected_codes,
        details=details,
    )


@dg.sensor(
    job_name="index_daily_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb", "tushare"},
    description="Tushare 指数日线源站 ready 后，触发 raw-by-code 更新任务。",
)
def index_daily_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    today = evaluated_at.date().isoformat()

    registered_trade_days = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_index_trade_days.name))
    )
    registered_index_codes = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_index_ts_codes.name))
    )
    if not registered_trade_days:
        return dg.SensorResult(
            skip_reason="没有注册指数交易日分区，无法触发指数日线更新。",
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                today=today,
                registered_trade_day_count=0,
                registered_code_count=len(registered_index_codes),
                target_trade_date=None,
                source_ready=None,
                source_row_count=None,
                pending_count=0,
                selected_codes=(),
                next_pending_offset=0,
            ),
        )
    if not registered_index_codes:
        return dg.SensorResult(
            skip_reason="没有注册指数代码分区，无法触发指数日线更新。",
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                today=today,
                registered_trade_day_count=len(registered_trade_days),
                registered_code_count=0,
                target_trade_date=None,
                source_ready=None,
                source_row_count=None,
                pending_count=0,
                selected_codes=(),
                next_pending_offset=0,
            ),
        )

    runnable_trade_dates = _recent_trade_dates(
        _runnable_trade_dates(registered_trade_days, evaluated_at)
    )
    if not runnable_trade_dates:
        return dg.SensorResult(
            skip_reason="没有符合当前时间窗口的指数交易日分区。",
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                today=today,
                registered_trade_day_count=len(registered_trade_days),
                registered_code_count=len(registered_index_codes),
                target_trade_date=None,
                source_ready=None,
                source_row_count=None,
                pending_count=0,
                selected_codes=(),
                next_pending_offset=0,
            ),
        )

    lake_root = context.resources.lake_root
    lake_root.ensure_available_for_run()
    raw_gap_audit = audit_index_daily_raw_gaps(
        lake_root_path=lake_root.root(),
        duckdb=context.resources.duckdb,
        registered_index_codes=registered_index_codes,
        trade_dates=runnable_trade_dates,
        index_basic_path=silver_index_basic_path(lake_root.root()),
        sample_limit=max(MAX_RUN_REQUESTS_PER_TICK, MAX_RAW_GAP_SAMPLE_COUNT),
    )
    target_trade_date = raw_gap_audit.first_missing_trade_date
    pending_count = raw_gap_audit.first_missing_code_count
    pending_codes = raw_gap_audit.first_missing_codes
    if raw_gap_audit.scan_error:
        return dg.SensorResult(
            skip_reason="指数日线 raw gap audit 扫描失败，暂不触发 raw 更新。",
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                today=today,
                registered_trade_day_count=len(registered_trade_days),
                registered_code_count=len(registered_index_codes),
                target_trade_date=target_trade_date,
                source_ready=None,
                source_row_count=None,
                pending_count=raw_gap_audit.missing_pair_count,
                selected_codes=(),
                next_pending_offset=0,
                audit_trade_date_count=raw_gap_audit.trade_date_count,
                audit_expected_pair_count=raw_gap_audit.expected_pair_count,
                audit_ready_pair_count=raw_gap_audit.ready_pair_count,
                audit_missing_pair_count=raw_gap_audit.missing_pair_count,
                audit_missing_file_count=raw_gap_audit.missing_file_count,
                audit_missing_trade_date_pair_count=(
                    raw_gap_audit.missing_trade_date_pair_count
                ),
                audit_no_raw_history_count=raw_gap_audit.no_raw_history_count,
                audit_no_raw_history_samples=raw_gap_audit.no_raw_history_codes[
                    :MAX_RAW_GAP_SAMPLE_COUNT
                ],
                raw_scan_error_code=raw_gap_audit.scan_error_code,
                raw_scan_error=raw_gap_audit.scan_error,
            ),
        )
    if raw_gap_audit.ready or target_trade_date is None:
        latest_runnable_trade_date = runnable_trade_dates[-1]
        latest_raw_status = check_index_daily_raw_files_for_trade_date(
            lake_root_path=lake_root.root(),
            duckdb=context.resources.duckdb,
            registered_index_codes=registered_index_codes,
            trade_date=latest_runnable_trade_date,
            index_basic_path=silver_index_basic_path(lake_root.root()),
        )
        if latest_raw_status.scan_error:
            return dg.SensorResult(
                skip_reason="指数日线 raw 目标交易日 presence 扫描失败，暂不触发 raw 更新。",
                cursor=_cursor_payload(
                    evaluated_at=evaluated_at,
                    today=today,
                    registered_trade_day_count=len(registered_trade_days),
                    registered_code_count=len(registered_index_codes),
                    target_trade_date=latest_runnable_trade_date,
                    source_ready=None,
                    source_row_count=None,
                    pending_count=latest_raw_status.registered_code_count,
                    selected_codes=(),
                    next_pending_offset=0,
                    audit_trade_date_count=raw_gap_audit.trade_date_count,
                    audit_expected_pair_count=raw_gap_audit.expected_pair_count,
                    audit_ready_pair_count=raw_gap_audit.ready_pair_count,
                    audit_missing_pair_count=raw_gap_audit.missing_pair_count,
                    audit_missing_file_count=raw_gap_audit.missing_file_count,
                    audit_missing_trade_date_pair_count=(
                        raw_gap_audit.missing_trade_date_pair_count
                    ),
                    audit_no_raw_history_count=raw_gap_audit.no_raw_history_count,
                    audit_no_raw_history_samples=raw_gap_audit.no_raw_history_codes[
                        :MAX_RAW_GAP_SAMPLE_COUNT
                    ],
                    raw_scan_error_code=latest_raw_status.scan_error_code,
                    raw_scan_error=latest_raw_status.scan_error,
                ),
            )
        if latest_raw_status.ready:
            return dg.SensorResult(
                skip_reason=(
                    "最近 60 个可运行指数交易日的 raw-by-code 本地连续性正常，"
                    "且最新目标交易日 raw 数据已经生成完成。"
                ),
                cursor=_cursor_payload(
                    evaluated_at=evaluated_at,
                    today=today,
                    registered_trade_day_count=len(registered_trade_days),
                    registered_code_count=len(registered_index_codes),
                    target_trade_date=None,
                    source_ready=None,
                    source_row_count=None,
                    pending_count=0,
                    selected_codes=(),
                    next_pending_offset=0,
                    audit_trade_date_count=raw_gap_audit.trade_date_count,
                    audit_expected_pair_count=raw_gap_audit.expected_pair_count,
                    audit_ready_pair_count=raw_gap_audit.ready_pair_count,
                    audit_missing_pair_count=raw_gap_audit.missing_pair_count,
                    audit_missing_file_count=raw_gap_audit.missing_file_count,
                    audit_missing_trade_date_pair_count=(
                        raw_gap_audit.missing_trade_date_pair_count
                    ),
                    audit_no_raw_history_count=raw_gap_audit.no_raw_history_count,
                    audit_no_raw_history_samples=raw_gap_audit.no_raw_history_codes[
                        :MAX_RAW_GAP_SAMPLE_COUNT
                    ],
                ),
            )
        target_trade_date = latest_runnable_trade_date
        pending_codes = tuple(
            sorted(
                set(
                    latest_raw_status.missing_file_codes
                    + latest_raw_status.missing_trade_date_codes
                )
            )
        )
        pending_count = len(pending_codes)

    source_readiness = check_index_daily_source_readiness(
        tushare=context.resources.tushare,
        trade_date=target_trade_date,
        checked_at=evaluated_at,
    )
    cursor_payload = load_sensor_cursor(context.cursor)
    if not source_readiness.is_ready:
        repair_selection = select_index_daily_pending_code_runs(
            cursor_payload=cursor_payload,
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            pending_codes=pending_codes,
            max_initial_run_requests=0,
            max_repair_run_requests=0,
        )
        return dg.SensorResult(
            skip_reason="Tushare 指数日线源站还没有返回有效数据。",
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                today=today,
                registered_trade_day_count=len(registered_trade_days),
                registered_code_count=len(registered_index_codes),
                target_trade_date=target_trade_date,
                source_ready=False,
                source_row_count=source_readiness.row_count,
                pending_count=pending_count,
                selected_codes=(),
                next_pending_offset=repair_selection.next_pending_offset,
                audit_trade_date_count=raw_gap_audit.trade_date_count,
                audit_expected_pair_count=raw_gap_audit.expected_pair_count,
                audit_ready_pair_count=raw_gap_audit.ready_pair_count,
                audit_missing_pair_count=raw_gap_audit.missing_pair_count,
                audit_missing_file_count=raw_gap_audit.missing_file_count,
                audit_missing_trade_date_pair_count=(
                    raw_gap_audit.missing_trade_date_pair_count
                ),
                audit_no_raw_history_count=raw_gap_audit.no_raw_history_count,
                audit_no_raw_history_samples=raw_gap_audit.no_raw_history_codes[
                    :MAX_RAW_GAP_SAMPLE_COUNT
                ],
                repair_state=repair_selection.repair_state,
                repair_new_code_count=repair_selection.new_code_count,
                repair_due_count=repair_selection.repair_due_count,
                repair_selected_count=repair_selection.repair_selected_count,
                repair_waiting_count=repair_selection.repair_waiting_count,
                repair_exhausted_count=repair_selection.repair_exhausted_count,
                repair_budget_limited_count=(
                    repair_selection.repair_budget_limited_count
                ),
                repair_state_code_count=repair_selection.repair_state_code_count,
                repair_cursor_code_limit_exceeded=(
                    repair_selection.repair_cursor_code_limit_exceeded
                ),
            ),
        )

    repair_selection = select_index_daily_pending_code_runs(
        target_trade_date=target_trade_date,
        evaluated_at=evaluated_at,
        cursor_payload=cursor_payload,
        pending_codes=pending_codes,
        max_initial_run_requests=MAX_RUN_REQUESTS_PER_TICK,
    )
    selected_codes = tuple(run.index_code for run in repair_selection.runs)
    cursor = _cursor_payload(
        evaluated_at=evaluated_at,
        today=today,
        registered_trade_day_count=len(registered_trade_days),
        registered_code_count=len(registered_index_codes),
        target_trade_date=target_trade_date,
        source_ready=True,
        source_row_count=source_readiness.row_count,
        pending_count=pending_count,
        selected_codes=selected_codes,
        next_pending_offset=repair_selection.next_pending_offset,
        audit_trade_date_count=raw_gap_audit.trade_date_count,
        audit_expected_pair_count=raw_gap_audit.expected_pair_count,
        audit_ready_pair_count=raw_gap_audit.ready_pair_count,
        audit_missing_pair_count=raw_gap_audit.missing_pair_count,
        audit_missing_file_count=raw_gap_audit.missing_file_count,
        audit_missing_trade_date_pair_count=raw_gap_audit.missing_trade_date_pair_count,
        audit_no_raw_history_count=raw_gap_audit.no_raw_history_count,
        audit_no_raw_history_samples=raw_gap_audit.no_raw_history_codes[
            :MAX_RAW_GAP_SAMPLE_COUNT
        ],
        repair_state=repair_selection.repair_state,
        repair_new_code_count=repair_selection.new_code_count,
        repair_due_count=repair_selection.repair_due_count,
        repair_selected_count=repair_selection.repair_selected_count,
        repair_waiting_count=repair_selection.repair_waiting_count,
        repair_exhausted_count=repair_selection.repair_exhausted_count,
        repair_budget_limited_count=repair_selection.repair_budget_limited_count,
        repair_state_code_count=repair_selection.repair_state_code_count,
        repair_cursor_code_limit_exceeded=(
            repair_selection.repair_cursor_code_limit_exceeded
        ),
    )
    if not selected_codes:
        skip_reason = "最早缺口指数交易日没有可选择的缺失指数代码。"
        if repair_selection.repair_cursor_code_limit_exceeded:
            skip_reason = (
                "指数日线 raw 补缺候选过多，疑似源端或本地系统性异常，"
                "暂不触发 repair。"
            )
        elif repair_selection.repair_waiting_count:
            skip_reason = "指数日线 raw 缺失代码尚未到达补缺 backoff 时间。"
        elif repair_selection.repair_exhausted_count:
            skip_reason = "指数日线 raw 缺失代码已达到当日补缺次数上限。"
        return dg.SensorResult(
            skip_reason=skip_reason,
            cursor=cursor,
        )

    return dg.SensorResult(
        run_requests=[
            build_run_request(
                partition_key=run.index_code,
                run_key=run.run_key,
                run_config=build_index_daily_update_job_run_config(
                    trade_date=target_trade_date,
                    write_mode="replace",
                ),
            )
            for run in repair_selection.runs
        ],
        cursor=cursor,
    )
