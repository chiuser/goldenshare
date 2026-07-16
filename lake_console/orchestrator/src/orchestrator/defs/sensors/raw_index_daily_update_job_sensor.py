from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    DEFAULT_CONTINUITY_WINDOW_LIMIT,
    ContinuityBatchReadiness,
    ContinuityDateReadiness,
    ContinuityExpectedDateWindow,
    ContinuityRegisteredGapStatus,
    build_continuity_cursor_details,
    build_registered_gap_status,
    load_expected_trade_date_window,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.prod_db.index_daily import (
    ProdIndexDailySourceReadiness,
    check_prod_index_daily_source_readiness,
)
from orchestrator.defs.run_contracts.configs import (
    build_raw_index_daily_update_job_run_config,
)
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.cursor_payloads import build_cursor_details
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.cn_a_trade_day_sensor import (
    INDEX_TRADE_DAY_MIN_DATE,
    SAME_DAY_PARTITION_REGISTER_START,
)
from orchestrator.defs.sensors.index_daily_raw_file_readiness import (
    raw_index_daily_lake_readiness_for_trade_dates,
)
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE


MAX_RUN_REQUESTS_PER_TICK = 1
SOURCE_MODE = "prod_core_db"
CURSOR_SAMPLE_LIMIT = 5


_COMPACT_CONTINUITY_KEYS = (
    "expected_start_date",
    "expected_end_date",
    "expected_count",
    "registered_count",
    "first_missing_registered_date",
    "registration_gap_class",
    "first_internal_missing_date",
    "first_trailing_unregistered_date",
    "trailing_unregistered_count",
    "actionable_registered_count",
    "last_registered_expected_date",
    "ready_through_trade_date",
    "first_not_ready_trade_date",
    "selected_trade_date",
    "blocked_reason",
    "batch_elapsed_ms",
    "scanned_file_count",
)

_COMPACT_RAW_SUMMARY_KEYS = (
    "row_count",
    "expected_code_count",
    "observed_code_count",
    "missing_code_count",
    "extra_code_count",
    "null_key_count",
    "date_mismatch_count",
    "duplicate_key_count",
    "scan_error_code",
    "scan_error",
)

_COMPACT_RAW_SAMPLE_KEYS = (
    "missing_columns",
    "unexpected_columns",
    "missing_code_samples",
    "extra_code_samples",
)


def _recent_trade_dates(
    trade_dates: tuple[str, ...],
    *,
    limit: int = DEFAULT_CONTINUITY_WINDOW_LIMIT,
) -> tuple[str, ...]:
    if limit <= 0:
        raise ValueError("limit must be positive.")
    return trade_dates[-limit:]


def _load_expected_index_trade_day_window(
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
            min_trade_date=INDEX_TRADE_DAY_MIN_DATE,
            same_day_register_start=SAME_DAY_PARTITION_REGISTER_START,
            window_limit=DEFAULT_CONTINUITY_WINDOW_LIMIT,
        )


def _index_trade_day_registered_gap(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime,
    registered_trade_days: tuple[str, ...],
) -> tuple[ContinuityExpectedDateWindow, ContinuityRegisteredGapStatus]:
    expected_window = _load_expected_index_trade_day_window(context, evaluated_at)
    gap_status = build_registered_gap_status(
        expected_trade_dates=expected_window.expected_trade_dates,
        registered_trade_dates=registered_trade_days,
    )
    return expected_window, gap_status


def _sample_values(
    values: object,
    *,
    sample_limit: int = CURSOR_SAMPLE_LIMIT,
) -> list[object]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return []
    return list(values[:sample_limit])


def _compact_continuity_status(
    continuity_status: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if continuity_status is None:
        return None
    payload = {
        key: continuity_status.get(key)
        for key in _COMPACT_CONTINUITY_KEYS
        if key in continuity_status
    }
    missing_registered_dates = _sample_values(
        continuity_status.get("missing_registered_dates")
    )
    if missing_registered_dates:
        payload["missing_registered_date_count"] = len(missing_registered_dates)
        payload["missing_registered_date_samples"] = missing_registered_dates
    return payload


def _compact_raw_status(
    raw_status: ContinuityDateReadiness | None,
) -> dict[str, object] | None:
    if raw_status is None:
        return None
    payload: dict[str, object] = {
        "trade_date": raw_status.trade_date,
        "ready": raw_status.ready,
        "materialized": raw_status.materialized,
        "checks_passed": raw_status.checks_passed,
        "reason": raw_status.reason,
        "failed_check_names": list(raw_status.failed_check_names),
        "missing_check_names": list(raw_status.missing_check_names),
        "missing_file_path_count": len(raw_status.missing_file_paths),
    }

    for key in _COMPACT_RAW_SUMMARY_KEYS:
        if key in raw_status.summary:
            payload[key] = raw_status.summary[key]
    for key in _COMPACT_RAW_SAMPLE_KEYS:
        sample = _sample_values(raw_status.summary.get(key))
        if sample:
            payload[key] = sample
    type_mismatches = raw_status.summary.get("type_mismatches")
    if isinstance(type_mismatches, Mapping) and type_mismatches:
        payload["type_mismatch_columns"] = list(type_mismatches.keys())[
            :CURSOR_SAMPLE_LIMIT
        ]
    return payload


def _compact_source_status(
    source_status: ProdIndexDailySourceReadiness | None,
) -> dict[str, object] | None:
    if source_status is None:
        return None
    return source_status.to_metadata()


def _blocked_component_for_reason(
    *,
    reason_code: str,
    selected_trade_date: str | None,
) -> str:
    if selected_trade_date is not None or reason_code in {"all_ready", "request_run"}:
        return "none"
    if reason_code in {
        "missing_registered_partition",
        "pending_registered_partition_tail",
        "no_registered_trade_day",
        "no_expected_trade_date",
    }:
        return "trade_day_partition"
    if reason_code == "no_registered_index_code":
        return "index_code_partition"
    if reason_code in {"missing_ready_baseline", "materialized_check_failed"}:
        return "raw_lake"
    if reason_code in {
        "scan_error",
        "source_empty",
        "null_key",
        "date_mismatch",
        "duplicate_key",
        "code_coverage",
        "not_ready",
    }:
        return "prod_core_db"
    return "raw_lake"


def _cursor_payload(
    *,
    evaluated_at: datetime,
    target_trade_date: str | None,
    selected_trade_date: str | None,
    registered_trade_day_count: int,
    registered_code_count: int,
    reason: str,
    reason_code: str,
    continuity_status: dict[str, object] | None = None,
    raw_status: ContinuityDateReadiness | None = None,
    raw_batch_status: ContinuityBatchReadiness | None = None,
    source_status: ProdIndexDailySourceReadiness | None = None,
) -> str:
    selected_count = 1 if selected_trade_date else 0
    details = build_cursor_details(
        sensor_name="raw_index_daily_update_job_sensor",
        job_name="raw_index_daily_update_job",
        asset_family="index_daily",
        partition_set=cn_a_index_trade_days.name,
        reason_code=reason_code,
        blocked_component=_blocked_component_for_reason(
            reason_code=reason_code,
            selected_trade_date=selected_trade_date,
        ),
        summary=reason,
        next_action=(
            "等待本次 run 完成。"
            if selected_trade_date
            else "按阻断组件修复上游状态，或等待下一次 sensor tick。"
        ),
        frontier=_compact_continuity_status(continuity_status),
        gate_statuses={
            "raw_lake": _compact_raw_status(raw_status),
            "prod_core_db": _compact_source_status(source_status),
        },
        evidence={
            "selected_trade_date": selected_trade_date,
            "registered_trade_day_count": registered_trade_day_count,
            "registered_code_count": registered_code_count,
            "source_mode": SOURCE_MODE,
            "max_run_requests_per_tick": MAX_RUN_REQUESTS_PER_TICK,
        },
        performance_ms={
            "raw_batch_elapsed_ms": raw_batch_status.elapsed_ms
            if raw_batch_status
            else None,
            "source_probe_elapsed_ms": source_status.elapsed_ms
            if source_status
            else None,
        },
    )
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=(
            SensorCursorDecision.REQUEST_RUNS
            if selected_count
            else SensorCursorDecision.SKIP
        ),
        target_date=target_trade_date,
        selected_count=selected_count,
        blocked_count=0 if selected_count else (1 if target_trade_date else 0),
        sample_keys=(selected_trade_date,) if selected_trade_date else (),
        details=details,
    )


def _registered_gap_skip_reason(gap_status: ContinuityRegisteredGapStatus) -> str:
    return (
        "指数交易日分区存在内部缺口，最早内部缺失日期为 "
        f"{gap_status.first_internal_missing_date}，暂不触发指数日线 raw by-date 更新。"
    )


@dg.sensor(
    job_name="raw_index_daily_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb", "prod_postgres"},
    description="prod core DB 指数日线 ready 后，触发 raw_index_daily by-date 更新任务。",
)
def raw_index_daily_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    registered_trade_days = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_index_trade_days.name))
    )
    registered_index_codes = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_index_ts_codes.name))
    )
    expected_window, gap_status = _index_trade_day_registered_gap(
        context,
        evaluated_at=evaluated_at,
        registered_trade_days=registered_trade_days,
    )
    empty_continuity_status = build_continuity_cursor_details(
        expected_window=expected_window,
        gap_status=gap_status,
        batch_readiness=None,
        selection=None,
    )
    if gap_status.has_internal_gap:
        reason = _registered_gap_skip_reason(gap_status)
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                target_trade_date=gap_status.first_internal_missing_date,
                selected_trade_date=None,
                registered_trade_day_count=len(registered_trade_days),
                registered_code_count=len(registered_index_codes),
                reason=reason,
                reason_code="missing_registered_partition",
                continuity_status=empty_continuity_status,
            ),
        )

    if not registered_trade_days:
        reason = "没有注册指数交易日分区，无法触发指数日线 raw by-date 更新。"
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                target_trade_date=None,
                selected_trade_date=None,
                registered_trade_day_count=0,
                registered_code_count=len(registered_index_codes),
                reason=reason,
                reason_code="no_registered_trade_day",
                continuity_status=empty_continuity_status,
            ),
        )
    if not registered_index_codes:
        reason = "没有注册指数代码分区，无法触发指数日线 raw by-date 更新。"
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                target_trade_date=None,
                selected_trade_date=None,
                registered_trade_day_count=len(registered_trade_days),
                registered_code_count=0,
                reason=reason,
                reason_code="no_registered_index_code",
                continuity_status=empty_continuity_status,
            ),
        )

    eligible_trade_dates = _recent_trade_dates(
        gap_status.actionable_expected_trade_dates
    )
    if not eligible_trade_dates:
        reason = "没有符合当前日期窗口的指数 expected trade date。"
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                target_trade_date=None,
                selected_trade_date=None,
                registered_trade_day_count=len(registered_trade_days),
                registered_code_count=len(registered_index_codes),
                reason=reason,
                reason_code="no_expected_trade_date",
                continuity_status=empty_continuity_status,
            ),
        )

    lake_root_path = context.resources.lake_root.root()
    duckdb_resource = context.resources.duckdb
    with duckdb_resource.connect() as connection:
        raw_batch_status = raw_index_daily_lake_readiness_for_trade_dates(
            connection,
            lake_root_path=lake_root_path,
            trade_dates=eligible_trade_dates,
            expected_index_codes=registered_index_codes,
        )
    selection = select_first_not_ready_trade_date(
        expected_trade_dates=eligible_trade_dates,
        readiness=raw_batch_status,
    )
    continuity_status = build_continuity_cursor_details(
        expected_window=expected_window,
        gap_status=gap_status,
        batch_readiness=raw_batch_status,
        selection=selection,
    )
    target_trade_date = selection.first_not_ready_trade_date
    raw_status = selection.selected_status

    if selection.selected_trade_date is None:
        if selection.blocked_reason == "materialized_check_failed":
            reason = (
                "目标 raw_index_daily 已生成过但 by-date blocking checks 未全绿，"
                "暂不自动覆盖，请人工处理。"
            )
        else:
            reason = "最近 10 个 expected index dates 的 raw_index_daily 都已经 ready。"
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                target_trade_date=target_trade_date,
                selected_trade_date=None,
                registered_trade_day_count=len(registered_trade_days),
                registered_code_count=len(registered_index_codes),
                reason=reason,
                reason_code=selection.blocked_reason or "all_ready",
                continuity_status=continuity_status,
                raw_status=raw_status,
                raw_batch_status=raw_batch_status,
            ),
        )

    target_trade_date = selection.selected_trade_date
    assert target_trade_date is not None
    if selection.ready_through_trade_date is None:
        reason = (
            "最近窗口缺少 raw_index_daily 已就绪基线，无法安全推断日更起点；"
            "请先完成 P3/P4 baseline 或人工确认。"
        )
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                target_trade_date=target_trade_date,
                selected_trade_date=None,
                registered_trade_day_count=len(registered_trade_days),
                registered_code_count=len(registered_index_codes),
                reason=reason,
                reason_code="missing_ready_baseline",
                continuity_status=continuity_status,
                raw_status=raw_status,
                raw_batch_status=raw_batch_status,
            ),
        )

    source_status = check_prod_index_daily_source_readiness(
        duckdb=context.resources.duckdb,
        prod_postgres=context.resources.prod_postgres,
        trade_date=target_trade_date,
        index_codes=registered_index_codes,
    )
    if not source_status.ready:
        reason = "prod core DB 指数日线 source readiness 未满足，暂不提交 raw 更新。"
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                target_trade_date=target_trade_date,
                selected_trade_date=None,
                registered_trade_day_count=len(registered_trade_days),
                registered_code_count=len(registered_index_codes),
                reason=reason,
                reason_code=source_status.reason,
                continuity_status=continuity_status,
                raw_status=raw_status,
                raw_batch_status=raw_batch_status,
                source_status=source_status,
            ),
        )

    run_request = build_run_request(
        run_key=build_asset_update_run_key(
            subject="raw_index_daily",
            unit_id=target_trade_date,
        ),
        partition_key=target_trade_date,
        run_config=build_raw_index_daily_update_job_run_config(
            partition_key=target_trade_date,
            write_mode="replace",
        ),
    )
    reason = "prod core DB 指数日线 source ready，提交 raw_index_daily by-date 更新。"
    return dg.SensorResult(
        run_requests=[run_request],
        cursor=_cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            selected_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            reason=reason,
            reason_code="request_run",
            continuity_status=continuity_status,
            raw_status=raw_status,
            raw_batch_status=raw_batch_status,
            source_status=source_status,
        ),
    )
