"""Stopped-by-default sensors for complete, same-day DC Raw partitions."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityExpectedDateWindow,
    ContinuityRegisteredGapStatus,
    ContinuitySelection,
    build_registered_gap_status,
    load_expected_trade_date_window,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.asset_guards.dc_board_lake_readiness import (
    batch_raw_dc_daily_lake_readiness,
    batch_raw_dc_index_lake_readiness,
    batch_raw_dc_member_lake_readiness,
)
from orchestrator.defs.asset_guards.dc_board_source_probe import (
    DcBoardProdCompletionResult,
    DcBoardTushareSourceResult,
    load_prod_dc_board_completion_snapshot,
    load_tushare_dc_index_daily_source_snapshot,
)
from orchestrator.defs.partitions import (
    cn_a_dc_daily_trade_days,
    cn_a_dc_index_trade_days,
    cn_a_dc_member_trade_days,
)
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.configs import (
    build_raw_dc_index_update_job_run_config,
)
from orchestrator.defs.run_contracts.cursor_payloads import (
    build_cursor_details,
    compact_batch_frontier,
    compact_continuity_frontier,
    cursor_runtime_state,
)
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
    load_sensor_cursor,
    sensor_cursor_details,
)
from orchestrator.defs.run_contracts.dc_board import (
    DC_BOARD_CURRENT_DAY_REFERENCE_NOT_BEFORE,
    DC_BOARD_REFERENCE_STABILITY_SECONDS,
    DC_BOARD_SENSOR_WINDOW_LIMIT,
    DC_DAILY_HISTORY_START_DATE,
    DC_INDEX_HISTORY_START_DATE,
    DC_MEMBER_HISTORY_START_DATE,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE

_PROD_COMPLETION_STATE_KEY = "dc_board_prod_completion"
_TUSHARE_SOURCE_STATE_KEY = "dc_board_tushare_source"


def _load_window(
    context: dg.SensorEvaluationContext,
    *,
    connection,
    evaluated_at: datetime,
    min_trade_date: str,
    partition_set: str,
) -> tuple[
    ContinuityExpectedDateWindow, tuple[str, ...], ContinuityRegisteredGapStatus
]:
    lake_root = context.resources.lake_root
    lake_root.ensure_available_for_run()
    expected_window = load_expected_trade_date_window(
        connection,
        silver_trade_calendar_path(lake_root.root()),
        evaluated_at=evaluated_at,
        min_trade_date=min_trade_date,
        same_day_register_start=None,
        window_limit=DC_BOARD_SENSOR_WINDOW_LIMIT,
    )
    registered = tuple(sorted(context.instance.get_dynamic_partitions(partition_set)))
    gap_status = build_registered_gap_status(
        expected_trade_dates=expected_window.expected_trade_dates,
        registered_trade_dates=registered,
    )
    return expected_window, registered, gap_status


def _cursor(
    *,
    sensor_name: str,
    job_name: str,
    evaluated_at: datetime,
    expected_window: ContinuityExpectedDateWindow | None,
    gap_status: ContinuityRegisteredGapStatus | None,
    batch_status: ContinuityBatchReadiness | None,
    selected_trade_date: str | None,
    reason_code: str,
    blocked_component: str,
    summary: str,
    next_action: str,
    partition_set: str,
    decision: SensorCursorDecision = SensorCursorDecision.SKIP,
    target_date: str | None = None,
    completion_status: DcBoardProdCompletionResult | None = None,
    source_status: DcBoardTushareSourceResult | None = None,
    runtime_state: Mapping[str, object] | None = None,
) -> str:
    evidence: dict[str, object] = {
        "expected_count": len(expected_window.expected_trade_dates)
        if expected_window
        else 0,
        "registered_count": len(gap_status.registered_trade_dates) if gap_status else 0,
    }
    performance_ms: dict[str, object] = {
        "duckdb_batch": batch_status.elapsed_ms if batch_status else None,
    }
    if completion_status is not None:
        completion_summary = completion_status.to_summary()
        completion_fingerprint = completion_summary.get("completion_fingerprint")
        if isinstance(completion_fingerprint, str):
            completion_summary["completion_fingerprint"] = completion_fingerprint[:12]
        evidence["prod_completion"] = completion_summary
        performance_ms["prod_completion"] = completion_status.elapsed_ms
    if source_status is not None:
        source_summary = source_status.to_summary()
        source_fingerprint = source_summary.get("source_fingerprint")
        if isinstance(source_fingerprint, str):
            source_summary["source_fingerprint"] = source_fingerprint[:12]
        evidence["tushare_source"] = source_summary
        performance_ms["tushare_source"] = source_status.elapsed_ms
    details = build_cursor_details(
        sensor_name=sensor_name,
        job_name=job_name,
        asset_family="dc_board",
        partition_set=partition_set,
        reason_code=reason_code,
        blocked_component=blocked_component,
        summary=summary,
        next_action=next_action,
        frontier=(
            compact_batch_frontier(
                batch_status, selected_trade_date=selected_trade_date
            )
            if batch_status is not None
            else compact_continuity_frontier(
                gap_status,
                selected_trade_date=selected_trade_date,
            )
        ),
        evidence=evidence,
        runtime_state=runtime_state,
        performance_ms=performance_ms,
    )
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_date,
        selected_count=1 if selected_trade_date else 0,
        blocked_count=0 if selected_trade_date else 1,
        details=details,
    )


def _upstream_blocks_target(
    selection: ContinuitySelection,
    *,
    target_trade_date: str,
) -> bool:
    first_not_ready_trade_date = selection.first_not_ready_trade_date
    return (
        first_not_ready_trade_date is not None
        and first_not_ready_trade_date <= target_trade_date
    )


def _select_target(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime,
    sensor_name: str,
    job_name: str,
    min_trade_date: str,
    batch_reader,
    partition_set: str,
) -> tuple[
    ContinuityExpectedDateWindow | None,
    tuple[str, ...],
    ContinuityRegisteredGapStatus | None,
    ContinuityBatchReadiness | None,
    str | None,
    dg.SensorResult | None,
]:
    """Select the first Raw gap while preserving the existing bounded frontier."""

    duckdb_resource = context.resources.duckdb
    with duckdb_resource.connect() as connection:
        expected_window, registered, gap_status = _load_window(
            context,
            connection=connection,
            evaluated_at=evaluated_at,
            min_trade_date=min_trade_date,
            partition_set=partition_set,
        )
        if not gap_status.ready:
            cursor = _cursor(
                sensor_name=sensor_name,
                job_name=job_name,
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                batch_status=None,
                selected_trade_date=None,
                reason_code="missing_registered_partition",
                blocked_component=partition_set,
                summary="板块 Raw 等待交易日分区注册。",
                next_action="先注册最早缺失的交易日分区。",
                target_date=gap_status.first_missing_registered_date,
                partition_set=partition_set,
            )
            return (
                expected_window,
                registered,
                gap_status,
                None,
                None,
                dg.SensorResult(
                    skip_reason=(
                        "板块 Raw 交易日分区尚未完整注册，最早缺失日期为 "
                        f"{gap_status.first_missing_registered_date}。"
                    ),
                    cursor=cursor,
                ),
            )
        batch_status = batch_reader(
            connection=connection,
            lake_root=context.resources.lake_root.root(),
            expected_trade_dates=expected_window.expected_trade_dates,
            registered_trade_days=registered,
        )
    selection = select_first_not_ready_trade_date(
        expected_trade_dates=expected_window.expected_trade_dates,
        readiness=batch_status,
    )
    selected_trade_date = selection.selected_trade_date
    if selected_trade_date is None:
        reason_code = (
            "materialized_check_failed" if selection.blocked_reason else "all_ready"
        )
        cursor = _cursor(
            sensor_name=sensor_name,
            job_name=job_name,
            evaluated_at=evaluated_at,
            expected_window=expected_window,
            gap_status=gap_status,
            batch_status=batch_status,
            selected_trade_date=None,
            reason_code=reason_code,
            blocked_component="raw_lake" if selection.blocked_reason else "none",
            summary=(
                "板块 Raw 最近窗口已就绪。"
                if reason_code == "all_ready"
                else "板块 Raw 已物化分区的 blocking check 未通过。"
            ),
            next_action=(
                "等待下一个交易日。"
                if reason_code == "all_ready"
                else "先修复最早失败的 Raw 分区，再等待下一轮。"
            ),
            target_date=selection.first_not_ready_trade_date,
            partition_set=partition_set,
        )
        return (
            expected_window,
            registered,
            gap_status,
            batch_status,
            None,
            dg.SensorResult(
                skip_reason="板块 Raw 窗口暂无可提交分区。",
                cursor=cursor,
            ),
        )
    return (
        expected_window,
        registered,
        gap_status,
        batch_status,
        selected_trade_date,
        None,
    )


def _source_runtime_state(
    *,
    prod_completion: Mapping[str, str] | None = None,
    tushare_source: Mapping[str, str] | None = None,
) -> dict[str, object]:
    state: dict[str, object] = {}
    if prod_completion is not None:
        state[_PROD_COMPLETION_STATE_KEY] = dict(prod_completion)
    if tushare_source is not None:
        state[_TUSHARE_SOURCE_STATE_KEY] = dict(tushare_source)
    return state


def _snapshot_state(
    *,
    trade_date: str,
    fingerprint: str,
    observed_at: datetime,
) -> dict[str, str]:
    return {
        "trade_date": trade_date,
        "fingerprint": fingerprint,
        "observed_at": observed_at.isoformat(),
    }


def _prior_snapshot_state(
    context: dg.SensorEvaluationContext,
    *,
    state_key: str,
    trade_date: str,
) -> dict[str, str] | None:
    details = sensor_cursor_details(load_sensor_cursor(context.cursor))
    raw_state = cursor_runtime_state(details).get(state_key)
    if not isinstance(raw_state, Mapping):
        return None
    observed_at = str(raw_state.get("observed_at") or "").strip()
    fingerprint = str(raw_state.get("fingerprint") or "").strip()
    if (
        str(raw_state.get("trade_date") or "") != trade_date
        or not observed_at
        or not fingerprint
    ):
        return None
    try:
        parsed_observed_at = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed_observed_at.tzinfo is None or parsed_observed_at.utcoffset() is None:
        return None
    return {"fingerprint": fingerprint, "observed_at": parsed_observed_at.isoformat()}


def _is_current_trade_date(*, evaluated_at: datetime, trade_date: str) -> bool:
    return evaluated_at.date().isoformat() == trade_date


def _submit_index_request(
    *,
    selected_trade_date: str,
    prod_completion_fingerprint: str,
    prod_completion_observed_at: str,
    tushare_source_fingerprint: str,
    tushare_source_observed_at: str,
) -> dg.RunRequest:
    return build_run_request(
        run_key=build_asset_update_run_key(
            subject="raw_tushare_dc_index_update",
            unit_id=selected_trade_date,
        ),
        partition_key=selected_trade_date,
        run_config=build_raw_dc_index_update_job_run_config(
            partition_key=selected_trade_date,
            trade_date=selected_trade_date,
            prod_completion_observed_at=prod_completion_observed_at,
            prod_completion_fingerprint=prod_completion_fingerprint,
            tushare_source_observed_at=tushare_source_observed_at,
            tushare_source_fingerprint=tushare_source_fingerprint,
        ),
    )


def _evaluate_index_sensor(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime,
) -> dg.SensorResult:
    sensor_name = "raw_tushare_dc_index_update_job_sensor"
    job_name = "raw_tushare_dc_index_update_job"
    partition_set = cn_a_dc_index_trade_days.name
    try:
        (
            expected_window,
            _registered,
            gap_status,
            batch_status,
            selected_trade_date,
            early_result,
        ) = _select_target(
            context,
            evaluated_at=evaluated_at,
            sensor_name=sensor_name,
            job_name=job_name,
            min_trade_date=DC_INDEX_HISTORY_START_DATE,
            batch_reader=batch_raw_dc_index_lake_readiness,
            partition_set=partition_set,
        )
        if early_result is not None:
            return early_result
        assert selected_trade_date is not None
        current_trade_date = _is_current_trade_date(
            evaluated_at=evaluated_at,
            trade_date=selected_trade_date,
        )
        if (
            current_trade_date
            and evaluated_at.timetz().replace(tzinfo=None)
            < DC_BOARD_CURRENT_DAY_REFERENCE_NOT_BEFORE
        ):
            cursor = _cursor(
                sensor_name=sensor_name,
                job_name=job_name,
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                batch_status=batch_status,
                selected_trade_date=None,
                reason_code="before_prod_completion_window",
                blocked_component="prod_core_db",
                summary="当天板块数据仍在等待 prod 完成状态观察窗口。",
                next_action="21:15 后开始第一次 prod 完成快照观察。",
                target_date=selected_trade_date,
                partition_set=partition_set,
            )
            return dg.SensorResult(
                skip_reason="板块 Raw 等待 21:15 后的 prod 完成观察。", cursor=cursor
            )

        completion_status = load_prod_dc_board_completion_snapshot(
            prod_postgres=context.resources.prod_postgres,
            trade_date=selected_trade_date,
        )
        if not completion_status.ready or completion_status.snapshot is None:
            cursor = _cursor(
                sensor_name=sensor_name,
                job_name=job_name,
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                batch_status=batch_status,
                selected_trade_date=None,
                reason_code=completion_status.reason_code,
                blocked_component="prod_core_db",
                summary="prod 板块完成状态尚未闭合。",
                next_action="等待 prod 同日 index、daily、member 三表内部闭合后重试。",
                target_date=selected_trade_date,
                partition_set=partition_set,
                completion_status=completion_status,
            )
            return dg.SensorResult(
                skip_reason="板块 Raw 等待 prod 同日完成状态。", cursor=cursor
            )

        runtime_state: Mapping[str, object] | None = None
        completion_state = _snapshot_state(
            trade_date=selected_trade_date,
            fingerprint=completion_status.snapshot.completion_fingerprint,
            observed_at=evaluated_at,
        )
        if current_trade_date:
            prior_completion = _prior_snapshot_state(
                context,
                state_key=_PROD_COMPLETION_STATE_KEY,
                trade_date=selected_trade_date,
            )
            if prior_completion is None:
                runtime_state = _source_runtime_state(
                    prod_completion=completion_state,
                )
                cursor = _cursor(
                    sensor_name=sensor_name,
                    job_name=job_name,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                    batch_status=batch_status,
                    selected_trade_date=None,
                    reason_code="prod_completion_pending_confirmation",
                    blocked_component="prod_core_db",
                    summary="已记录第一份 prod 板块完成快照，等待稳定确认。",
                    next_action=f"至少等待 {DC_BOARD_REFERENCE_STABILITY_SECONDS} 秒后再确认完成状态未变化。",
                    target_date=selected_trade_date,
                    partition_set=partition_set,
                    completion_status=completion_status,
                    runtime_state=runtime_state,
                )
                return dg.SensorResult(
                    skip_reason="板块 Raw 已记录第一份 prod 完成快照。", cursor=cursor
                )
            prior_observed_at = datetime.fromisoformat(prior_completion["observed_at"])
            elapsed_seconds = (evaluated_at - prior_observed_at).total_seconds()
            if elapsed_seconds < DC_BOARD_REFERENCE_STABILITY_SECONDS:
                completion_state = dict(prior_completion)
                runtime_state = _source_runtime_state(
                    prod_completion=completion_state,
                )
                cursor = _cursor(
                    sensor_name=sensor_name,
                    job_name=job_name,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                    batch_status=batch_status,
                    selected_trade_date=None,
                    reason_code="prod_completion_pending_confirmation",
                    blocked_component="prod_core_db",
                    summary="prod 板块完成快照尚未达到稳定确认间隔。",
                    next_action=f"等待剩余 {max(0, int(DC_BOARD_REFERENCE_STABILITY_SECONDS - elapsed_seconds))} 秒后重试。",
                    target_date=selected_trade_date,
                    partition_set=partition_set,
                    completion_status=completion_status,
                    runtime_state=runtime_state,
                )
                return dg.SensorResult(
                    skip_reason="板块 Raw 等待 prod 完成快照稳定确认。", cursor=cursor
                )
            if (
                prior_completion["fingerprint"]
                != completion_status.snapshot.completion_fingerprint
            ):
                runtime_state = _source_runtime_state(
                    prod_completion=completion_state,
                )
                cursor = _cursor(
                    sensor_name=sensor_name,
                    job_name=job_name,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                    batch_status=batch_status,
                    selected_trade_date=None,
                    reason_code="prod_completion_changed",
                    blocked_component="prod_core_db",
                    summary="第二份 prod 板块完成快照与第一次不同，重新开始观察。",
                    next_action=f"至少等待 {DC_BOARD_REFERENCE_STABILITY_SECONDS} 秒后再确认新快照。",
                    target_date=selected_trade_date,
                    partition_set=partition_set,
                    completion_status=completion_status,
                    runtime_state=runtime_state,
                )
                return dg.SensorResult(
                    skip_reason="板块 Raw 发现 prod 完成快照变化。", cursor=cursor
                )

        source_status = load_tushare_dc_index_daily_source_snapshot(
            tushare=context.resources.tushare,
            trade_date=selected_trade_date,
            prod_completion=completion_status.snapshot,
        )
        if not source_status.ready or source_status.snapshot is None:
            runtime_state = _source_runtime_state(prod_completion=completion_state)
            cursor = _cursor(
                sensor_name=sensor_name,
                job_name=job_name,
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                batch_status=batch_status,
                selected_trade_date=None,
                reason_code=source_status.reason_code,
                blocked_component="tushare_dc_board",
                summary="Tushare 板块目录或行情自身结构尚未闭合。",
                next_action="等待源站完整后重新读取；不要提交结构不完整的 Raw run。",
                target_date=selected_trade_date,
                partition_set=partition_set,
                completion_status=completion_status,
                source_status=source_status,
                runtime_state=runtime_state,
            )
            return dg.SensorResult(
                skip_reason="板块 Raw 等待 Tushare 源结构闭合。", cursor=cursor
            )

        source_state = _snapshot_state(
            trade_date=selected_trade_date,
            fingerprint=source_status.snapshot.source_fingerprint,
            observed_at=evaluated_at,
        )
        if not source_status.content_matches_prod:
            prior_source = _prior_snapshot_state(
                context,
                state_key=_TUSHARE_SOURCE_STATE_KEY,
                trade_date=selected_trade_date,
            )
            runtime_state = _source_runtime_state(
                prod_completion=completion_state,
                tushare_source=source_state,
            )
            if prior_source is None:
                cursor = _cursor(
                    sensor_name=sensor_name,
                    job_name=job_name,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                    batch_status=batch_status,
                    selected_trade_date=None,
                    reason_code="tushare_source_pending_confirmation",
                    blocked_component="tushare_dc_board",
                    summary="Tushare 与 prod 内容不同，已记录第一份 Tushare 源快照。",
                    next_action="下一轮重新读取 Tushare；源快照稳定后按 Tushare 事实提交。",
                    target_date=selected_trade_date,
                    partition_set=partition_set,
                    completion_status=completion_status,
                    source_status=source_status,
                    runtime_state=runtime_state,
                )
                return dg.SensorResult(
                    skip_reason="板块 Raw 等待第二份 Tushare 源快照。", cursor=cursor
                )
            if prior_source["fingerprint"] != source_status.snapshot.source_fingerprint:
                cursor = _cursor(
                    sensor_name=sensor_name,
                    job_name=job_name,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                    batch_status=batch_status,
                    selected_trade_date=None,
                    reason_code="tushare_source_changed",
                    blocked_component="tushare_dc_board",
                    summary="第二份 Tushare 源快照发生变化，重新开始稳定观察。",
                    next_action="下一轮重新读取 Tushare，直到完整业务行快照稳定。",
                    target_date=selected_trade_date,
                    partition_set=partition_set,
                    completion_status=completion_status,
                    source_status=source_status,
                    runtime_state=runtime_state,
                )
                return dg.SensorResult(
                    skip_reason="板块 Raw 发现 Tushare 源快照变化。", cursor=cursor
                )
        else:
            runtime_state = _source_runtime_state(
                prod_completion=completion_state,
                tushare_source=source_state,
            )

        cursor = _cursor(
            sensor_name=sensor_name,
            job_name=job_name,
            evaluated_at=evaluated_at,
            expected_window=expected_window,
            gap_status=gap_status,
            batch_status=batch_status,
            selected_trade_date=selected_trade_date,
            reason_code="request_run",
            blocked_component="none",
            summary=(
                "prod 完成状态稳定，Tushare 源快照也已稳定，提交板块目录更新。"
                if not source_status.content_matches_prod
                else "prod 完成状态稳定，Tushare 完整源快照可用，提交板块目录更新。"
            ),
            next_action="运行 raw_tushare_dc_index 后，由 daily/member 等待同日目录就绪。",
            target_date=selected_trade_date,
            partition_set=partition_set,
            decision=SensorCursorDecision.REQUEST_RUNS,
            completion_status=completion_status,
            source_status=source_status,
            runtime_state=runtime_state,
        )
        return dg.SensorResult(
            run_requests=[
                _submit_index_request(
                    selected_trade_date=selected_trade_date,
                    prod_completion_fingerprint=(
                        completion_status.snapshot.completion_fingerprint
                    ),
                    prod_completion_observed_at=completion_state["observed_at"],
                    tushare_source_fingerprint=source_status.snapshot.source_fingerprint,
                    tushare_source_observed_at=source_state["observed_at"],
                )
            ],
            cursor=cursor,
        )
    except Exception as exc:  # noqa: BLE001 - sensor must fail closed.
        cursor = _cursor(
            sensor_name=sensor_name,
            job_name=job_name,
            evaluated_at=evaluated_at,
            expected_window=None,
            gap_status=None,
            batch_status=None,
            selected_trade_date=None,
            reason_code="dc_index_sensor_error",
            blocked_component="sensor",
            summary="板块目录 sensor 执行失败。",
            next_action="检查 cursor 的最小错误证据和运行日志后重试。",
            partition_set=partition_set,
        )
        return dg.SensorResult(skip_reason=str(exc), cursor=cursor)


def _evaluate_dependent_sensor(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime,
    sensor_name: str,
    job_name: str,
    min_trade_date: str,
    batch_reader,
    partition_set: str,
) -> dg.SensorResult:
    try:
        (
            expected_window,
            _registered,
            gap_status,
            batch_status,
            selected_trade_date,
            early_result,
        ) = _select_target(
            context,
            evaluated_at=evaluated_at,
            sensor_name=sensor_name,
            job_name=job_name,
            min_trade_date=min_trade_date,
            batch_reader=batch_reader,
            partition_set=partition_set,
        )
        if early_result is not None:
            return early_result
        assert selected_trade_date is not None
        duckdb_resource = context.resources.duckdb
        with duckdb_resource.connect() as connection:
            index_registered = tuple(
                sorted(
                    context.instance.get_dynamic_partitions(
                        cn_a_dc_index_trade_days.name
                    )
                )
            )
            index_batch = batch_raw_dc_index_lake_readiness(
                connection=connection,
                lake_root=context.resources.lake_root.root(),
                expected_trade_dates=expected_window.expected_trade_dates,
                registered_trade_days=index_registered,
            )
        index_selection = select_first_not_ready_trade_date(
            expected_trade_dates=expected_window.expected_trade_dates,
            readiness=index_batch,
        )
        if _upstream_blocks_target(
            index_selection, target_trade_date=selected_trade_date
        ):
            cursor = _cursor(
                sensor_name=sensor_name,
                job_name=job_name,
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                batch_status=index_batch,
                selected_trade_date=None,
                reason_code=(
                    "materialized_check_failed"
                    if index_selection.blocked_reason
                    else "upstream_index_not_ready"
                ),
                blocked_component="raw_tushare_dc_index",
                summary="同日板块目录尚未就绪，daily/member 不提交。",
                next_action="先完成同日 raw_tushare_dc_index，再由本 sensor 自然触发。",
                target_date=selected_trade_date,
                partition_set=partition_set,
            )
            return dg.SensorResult(
                skip_reason="板块 Raw 等待同日 raw_tushare_dc_index。", cursor=cursor
            )
        cursor = _cursor(
            sensor_name=sensor_name,
            job_name=job_name,
            evaluated_at=evaluated_at,
            expected_window=expected_window,
            gap_status=gap_status,
            batch_status=batch_status,
            selected_trade_date=selected_trade_date,
            reason_code="request_run",
            blocked_component="none",
            summary="同日板块目录已就绪，提交下游 Raw 更新。",
            next_action="运行选中的同日分区。",
            target_date=selected_trade_date,
            partition_set=partition_set,
            decision=SensorCursorDecision.REQUEST_RUNS,
        )
        return dg.SensorResult(
            run_requests=[
                build_run_request(
                    run_key=build_asset_update_run_key(
                        subject=job_name.removesuffix("_job"),
                        unit_id=selected_trade_date,
                    ),
                    partition_key=selected_trade_date,
                )
            ],
            cursor=cursor,
        )
    except Exception as exc:  # noqa: BLE001 - sensor must fail closed.
        cursor = _cursor(
            sensor_name=sensor_name,
            job_name=job_name,
            evaluated_at=evaluated_at,
            expected_window=None,
            gap_status=None,
            batch_status=None,
            selected_trade_date=None,
            reason_code="dc_board_dependent_sensor_error",
            blocked_component="sensor",
            summary="板块下游 Raw sensor 执行失败。",
            next_action="检查 cursor 的最小错误证据和运行日志后重试。",
            partition_set=partition_set,
        )
        return dg.SensorResult(skip_reason=str(exc), cursor=cursor)


@dg.sensor(
    job_name="raw_tushare_dc_index_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb", "tushare", "prod_postgres"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
)
def raw_tushare_dc_index_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return _evaluate_index_sensor(
        context, evaluated_at=datetime.now(CN_A_SENSOR_TIMEZONE)
    )


@dg.sensor(
    job_name="raw_tushare_dc_member_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
)
def raw_tushare_dc_member_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return _evaluate_dependent_sensor(
        context,
        evaluated_at=datetime.now(CN_A_SENSOR_TIMEZONE),
        sensor_name="raw_tushare_dc_member_update_job_sensor",
        job_name="raw_tushare_dc_member_update_job",
        min_trade_date=DC_MEMBER_HISTORY_START_DATE,
        batch_reader=batch_raw_dc_member_lake_readiness,
        partition_set=cn_a_dc_member_trade_days.name,
    )


@dg.sensor(
    job_name="raw_tushare_dc_daily_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
)
def raw_tushare_dc_daily_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return _evaluate_dependent_sensor(
        context,
        evaluated_at=datetime.now(CN_A_SENSOR_TIMEZONE),
        sensor_name="raw_tushare_dc_daily_update_job_sensor",
        job_name="raw_tushare_dc_daily_update_job",
        min_trade_date=DC_DAILY_HISTORY_START_DATE,
        batch_reader=batch_raw_dc_daily_lake_readiness,
        partition_set=cn_a_dc_daily_trade_days.name,
    )


__all__ = [
    "raw_tushare_dc_daily_update_job_sensor",
    "raw_tushare_dc_index_update_job_sensor",
    "raw_tushare_dc_member_update_job_sensor",
]
