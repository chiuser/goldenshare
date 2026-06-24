from __future__ import annotations

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
from orchestrator.defs.asset_guards.market_major_indices_lake_readiness import (
    batch_silver_index_daily_lake_readiness,
)
from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.paths import silver_trade_calendar_path
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
from orchestrator.defs.sensors.cn_a_trade_day_sensor import (
    INDEX_TRADE_DAY_MIN_DATE,
    SAME_DAY_PARTITION_REGISTER_START,
)
from orchestrator.defs.sensors.index_daily_raw_file_readiness import (
    raw_index_daily_lake_readiness_for_trade_dates,
)
from orchestrator.defs.sensors.readiness import (
    CN_A_SENSOR_TIMEZONE,
)


MAX_RUN_REQUESTS_PER_TICK = 1


def _asset_status_payload(
    status: ContinuityDateReadiness | None,
) -> dict[str, object] | None:
    if status is None:
        return None
    return status.to_cursor_details()


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


def _recent_trade_dates(
    trade_dates: tuple[str, ...],
    *,
    limit: int = DEFAULT_CONTINUITY_WINDOW_LIMIT,
) -> tuple[str, ...]:
    if limit <= 0:
        raise ValueError("limit must be positive.")
    return trade_dates[-limit:]


def _cursor_payload(
    *,
    evaluated_at: datetime,
    target_trade_date: str | None,
    selected_trade_date: str | None,
    registered_trade_day_count: int,
    registered_code_count: int,
    reason: str,
    reason_code: str,
    continuity_details: dict[str, object] | None = None,
    raw_status: ContinuityDateReadiness | None = None,
    raw_batch_status: ContinuityBatchReadiness | None = None,
    silver_status: ContinuityDateReadiness | None = None,
    silver_batch_status: ContinuityBatchReadiness | None = None,
) -> str:
    selected_count = 1 if selected_trade_date else 0
    details: dict[str, Any] = {
        "selected_trade_date": selected_trade_date,
        "registered_trade_day_count": registered_trade_day_count,
        "registered_code_count": registered_code_count,
        "reason_code": reason_code,
        "max_run_requests_per_tick": MAX_RUN_REQUESTS_PER_TICK,
        "continuity_status": continuity_details,
        "raw_status": raw_status.to_cursor_details() if raw_status else None,
        "raw_batch_status": (
            raw_batch_status.to_cursor_details() if raw_batch_status else None
        ),
        "silver_batch_status": (
            silver_batch_status.to_cursor_details() if silver_batch_status else None
        ),
        "silver_status": _asset_status_payload(silver_status),
    }
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


def _registered_gap_skip_reason(
    gap_status: ContinuityRegisteredGapStatus,
) -> str:
    return (
        "指数交易日分区存在缺口，最早缺失日期为 "
        f"{gap_status.first_missing_registered_date}，暂不触发指数日线 silver 更新。"
    )


@dg.sensor(
    job_name="silver_index_daily_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description="指数日线 raw_index_daily by-date ready 后，触发 silver 分区生成任务。",
)
def silver_index_daily_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
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
    empty_continuity_details = build_continuity_cursor_details(
        expected_window=expected_window,
        gap_status=gap_status,
        batch_readiness=None,
        selection=None,
    )
    if gap_status.first_missing_registered_date is not None:
        reason = _registered_gap_skip_reason(gap_status)
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                target_trade_date=gap_status.first_missing_registered_date,
                selected_trade_date=None,
                registered_trade_day_count=len(registered_trade_days),
                registered_code_count=len(registered_index_codes),
                reason=reason,
                reason_code="missing_registered_partition",
                continuity_details=empty_continuity_details,
            ),
        )

    if not registered_trade_days:
        reason = "没有注册指数交易日分区，无法触发指数日线 silver 生成。"
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
                continuity_details=empty_continuity_details,
            ),
        )
    if not registered_index_codes:
        reason = "没有注册指数代码分区，无法触发指数日线 silver 生成。"
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
                continuity_details=empty_continuity_details,
            ),
        )

    eligible_trade_dates = _recent_trade_dates(expected_window.expected_trade_dates)
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
                continuity_details=empty_continuity_details,
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
    raw_selection = select_first_not_ready_trade_date(
        expected_trade_dates=eligible_trade_dates,
        readiness=raw_batch_status,
    )
    continuity_details = build_continuity_cursor_details(
        expected_window=expected_window,
        gap_status=gap_status,
        batch_readiness=raw_batch_status,
        selection=raw_selection,
    )
    raw_status = raw_selection.selected_status
    if raw_selection.selected_trade_date is not None:
        reason = "指数日线 silver 等待 raw_index_daily by-date readiness。"
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                target_trade_date=raw_selection.selected_trade_date,
                selected_trade_date=None,
                registered_trade_day_count=len(registered_trade_days),
                registered_code_count=len(registered_index_codes),
                reason=reason,
                reason_code=raw_status.reason if raw_status else "raw_not_ready",
                continuity_details=continuity_details,
                raw_status=raw_status,
                raw_batch_status=raw_batch_status,
            ),
        )
    if raw_selection.blocked_reason == "materialized_check_failed":
        reason = (
            "目标 raw_index_daily 已生成过但 by-date blocking checks 未全绿，"
            "暂不生成 silver。"
        )
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                target_trade_date=raw_selection.first_not_ready_trade_date,
                selected_trade_date=None,
                registered_trade_day_count=len(registered_trade_days),
                registered_code_count=len(registered_index_codes),
                reason=reason,
                reason_code="raw_materialized_check_failed",
                continuity_details=continuity_details,
                raw_status=raw_status,
                raw_batch_status=raw_batch_status,
            ),
        )

    with duckdb_resource.connect() as connection:
        silver_batch_status = batch_silver_index_daily_lake_readiness(
            connection=connection,
            lake_root_path=lake_root_path,
            expected_trade_dates=eligible_trade_dates,
            registered_index_codes=registered_index_codes,
        )
    silver_selection = select_first_not_ready_trade_date(
        expected_trade_dates=eligible_trade_dates,
        readiness=silver_batch_status,
    )
    silver_continuity_details = build_continuity_cursor_details(
        expected_window=expected_window,
        gap_status=gap_status,
        batch_readiness=silver_batch_status,
        selection=silver_selection,
    )
    target_trade_date = silver_selection.selected_trade_date
    silver_status = silver_selection.selected_status
    if target_trade_date is None and silver_selection.blocked_reason is None:
        reason = "最近 10 个 expected index dates 的 silver_index_daily 分区都已经 ready。"
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                target_trade_date=None,
                selected_trade_date=None,
                registered_trade_day_count=len(registered_trade_days),
                registered_code_count=len(registered_index_codes),
                reason=reason,
                reason_code="all_ready",
                continuity_details=silver_continuity_details,
                raw_batch_status=raw_batch_status,
                silver_batch_status=silver_batch_status,
            ),
        )

    if silver_selection.blocked_reason == "materialized_check_failed":
        reason = (
            "目标指数交易日的 silver_index_daily 已生成但 blocking checks 未全绿，"
            "暂不自动重跑，请先人工处理失败检查。"
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
                reason_code=silver_status.reason if silver_status else "silver_not_ready",
                continuity_details=silver_continuity_details,
                raw_batch_status=raw_batch_status,
                silver_batch_status=silver_batch_status,
                silver_status=silver_status,
            ),
        )

    if target_trade_date is None or silver_status is None:
        reason = "silver_index_daily readiness map 缺少目标日期状态，暂不触发。"
        return dg.SensorResult(
            skip_reason=reason,
            cursor=_cursor_payload(
                evaluated_at=evaluated_at,
                target_trade_date=silver_selection.first_not_ready_trade_date,
                selected_trade_date=None,
                registered_trade_day_count=len(registered_trade_days),
                registered_code_count=len(registered_index_codes),
                reason=reason,
                reason_code=silver_status.reason if silver_status else "silver_status_missing",
                continuity_details=silver_continuity_details,
                raw_batch_status=raw_batch_status,
                silver_batch_status=silver_batch_status,
                silver_status=silver_status,
            ),
        )

    return dg.SensorResult(
        run_requests=[
            build_run_request(
                partition_key=target_trade_date,
                run_key=build_asset_update_run_key(
                    subject="silver_index_daily",
                    unit_id=target_trade_date,
                ),
            )
        ],
        cursor=_cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            selected_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            reason="raw_index_daily by-date ready，提交 silver_index_daily 生成。",
            reason_code="request_run",
            continuity_details=silver_continuity_details,
            raw_batch_status=raw_batch_status,
            silver_batch_status=silver_batch_status,
            silver_status=silver_status,
        ),
    )
