"""Bounded Raw/Silver sensors for major-index minute partitions."""

from dataclasses import dataclass
from datetime import datetime

import dagster as dg
from dagster._core.storage.dagster_run import RunsFilter

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityExpectedDateWindow,
    ContinuityRegisteredGapStatus,
    build_registered_gap_status,
    load_expected_trade_date_window,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.asset_guards.major_index_mins_lake_readiness import (
    batch_raw_major_index_mins_lake_readiness,
    batch_silver_major_index_mins_lake_readiness,
)
from orchestrator.defs.asset_guards.major_index_mins_source_probe import (
    MajorIndexMinsSourceProbeResult,
    probe_major_index_mins_source,
)
from orchestrator.defs.partitions import cn_major_index_mins_trade_days
from orchestrator.defs.paths import (
    raw_major_index_mins_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.run_contracts.cursor_payloads import (
    build_cursor_details,
    compact_batch_frontier,
    compact_continuity_frontier,
    compact_date_readiness,
)
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_DAILY_PROBE_WINDOW_LIMIT,
    MAJOR_INDEX_MINS_HISTORY_START_DATE,
    MAJOR_INDEX_MINS_RAW_AUTO_RETRY_LIMIT,
    MAJOR_INDEX_MINS_RAW_JOB_NAME,
    MAJOR_INDEX_MINS_RAW_RETRY_ATTEMPT_SCOPE,
    MAJOR_INDEX_MINS_SILVER_JOB_NAME,
    MAJOR_INDEX_MINS_SOURCE_FREQS,
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
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE
from orchestrator.defs.tushare_request_policy import TushareRequestPolicy

_SOURCE_PROBE_POLICY = TushareRequestPolicy(
    minimum_interval_seconds=0.13,
    max_retries=3,
    max_requests=20,
    max_elapsed_seconds=30,
)

_DAGSTER_PARTITION_TAG = "dagster/partition"
_DAGSTER_RUN_KEY_TAG = "dagster/run_key"
_RAW_RUN_SUBJECT = MAJOR_INDEX_MINS_RAW_JOB_NAME.removesuffix("_job")
_ACTIVE_RUN_STATUSES = frozenset(
    {
        dg.DagsterRunStatus.NOT_STARTED,
        dg.DagsterRunStatus.QUEUED,
        dg.DagsterRunStatus.STARTING,
        dg.DagsterRunStatus.STARTED,
        dg.DagsterRunStatus.CANCELING,
    }
)
_RETRYABLE_TERMINAL_RUN_STATUSES = frozenset(
    {dg.DagsterRunStatus.FAILURE, dg.DagsterRunStatus.CANCELED}
)


@dataclass(frozen=True, slots=True)
class _RawRunAttempt:
    attempt: int | None
    reason_code: str

    @property
    def can_submit(self) -> bool:
        return self.attempt is not None


def _raw_run_candidate_keys(trade_date: str) -> tuple[str, ...]:
    return (
        build_asset_update_run_key(subject=_RAW_RUN_SUBJECT, unit_id=trade_date),
        *(
            build_repair_attempt_run_key(
                subject=_RAW_RUN_SUBJECT,
                repair_scope_id=trade_date,
                attempt_scope=MAJOR_INDEX_MINS_RAW_RETRY_ATTEMPT_SCOPE,
                attempt=attempt,
            )
            for attempt in range(1, MAJOR_INDEX_MINS_RAW_AUTO_RETRY_LIMIT + 1)
        ),
    )


def _select_raw_run_attempt(
    instance: dg.DagsterInstance,
    *,
    trade_date: str,
) -> _RawRunAttempt:
    candidate_keys = _raw_run_candidate_keys(trade_date)
    records = instance.get_run_records(
        filters=RunsFilter(
            job_name=MAJOR_INDEX_MINS_RAW_JOB_NAME,
            tags={
                _DAGSTER_PARTITION_TAG: trade_date,
            },
        ),
        limit=len(candidate_keys),
    )
    records_by_key: dict[str, object] = {}
    for record in records:
        dagster_run = record.dagster_run
        run_key = str(dagster_run.tags.get(_DAGSTER_RUN_KEY_TAG, "")).strip()
        if run_key not in candidate_keys or run_key in records_by_key:
            return _RawRunAttempt(None, "raw_retry_identity_conflict")
        records_by_key[run_key] = dagster_run

    for candidate_index, run_key in enumerate(candidate_keys):
        dagster_run = records_by_key.get(run_key)
        later_keys = candidate_keys[candidate_index + 1 :]
        if dagster_run is None:
            if any(key in records_by_key for key in later_keys):
                return _RawRunAttempt(None, "raw_retry_identity_gap")
            return _RawRunAttempt(
                candidate_index,
                "initial_run" if candidate_index == 0 else "retry_run",
            )
        status = getattr(dagster_run, "status", None)
        if status in _ACTIVE_RUN_STATUSES:
            return _RawRunAttempt(None, "raw_run_active")
        if status == dg.DagsterRunStatus.SUCCESS:
            return _RawRunAttempt(None, "raw_run_success_without_files")
        if status not in _RETRYABLE_TERMINAL_RUN_STATUSES:
            return _RawRunAttempt(None, "raw_run_status_not_retryable")

    return _RawRunAttempt(None, "raw_retry_exhausted")


def _missing_raw_source_freqs(*, lake_root, trade_date: str) -> tuple[str, ...]:
    return tuple(
        source_freq
        for source_freq in MAJOR_INDEX_MINS_SOURCE_FREQS
        if not raw_major_index_mins_path(
            lake_root,
            source_freq,
            trade_date,
        ).exists()
    )


def _load_window(
    context: dg.SensorEvaluationContext,
    *,
    connection,
    evaluated_at: datetime,
) -> tuple[
    ContinuityExpectedDateWindow,
    tuple[str, ...],
    ContinuityRegisteredGapStatus,
]:
    lake_root = context.resources.lake_root
    lake_root.ensure_available_for_run()
    expected_window = load_expected_trade_date_window(
        connection,
        silver_trade_calendar_path(lake_root.root()),
        evaluated_at=evaluated_at,
        min_trade_date=MAJOR_INDEX_MINS_HISTORY_START_DATE,
        same_day_register_start=None,
        window_limit=MAJOR_INDEX_MINS_DAILY_PROBE_WINDOW_LIMIT,
    )
    registered = tuple(
        sorted(
            context.instance.get_dynamic_partitions(cn_major_index_mins_trade_days.name)
        )
    )
    gap_status = build_registered_gap_status(
        expected_trade_dates=expected_window.expected_trade_dates,
        registered_trade_dates=registered,
    )
    return expected_window, registered, gap_status


def _source_summary(
    source: MajorIndexMinsSourceProbeResult | None,
) -> dict[str, object] | None:
    if source is None:
        return None
    return {
        "source_freq": source.source_freq,
        "ready": source.ready,
        "reason_code": source.reason_code,
        "expected_code_count": source.expected_code_count,
        "returned_code_count": source.returned_code_count,
        "request_count": source.request_count,
        "retry_count": source.retry_count,
        "elapsed_ms": source.elapsed_ms,
    }


def _cursor(
    *,
    sensor_name: str,
    job_name: str,
    evaluated_at: datetime,
    expected_window: ContinuityExpectedDateWindow | None,
    gap_status: ContinuityRegisteredGapStatus | None,
    selected_status: object | None,
    target_date: str | None,
    selected_trade_date: str | None,
    reason_code: str,
    blocked_component: str,
    summary: str,
    next_action: str,
    lake_batch: ContinuityBatchReadiness | None = None,
    raw_batch: ContinuityBatchReadiness | None = None,
    silver_batch: ContinuityBatchReadiness | None = None,
    source: MajorIndexMinsSourceProbeResult | None = None,
    run_attempt: int | None = None,
    missing_source_freqs: tuple[str, ...] = (),
) -> str:
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=(
            SensorCursorDecision.REQUEST_RUNS
            if selected_trade_date
            else SensorCursorDecision.SKIP
        ),
        target_date=target_date,
        selected_count=1 if selected_trade_date else 0,
        blocked_count=0 if selected_trade_date else (1 if target_date else 0),
        sample_keys=(selected_trade_date,) if selected_trade_date else (),
        details=build_cursor_details(
            sensor_name=sensor_name,
            job_name=job_name,
            asset_family="major_index_mins",
            partition_set=cn_major_index_mins_trade_days.name,
            reason_code=reason_code,
            blocked_component=blocked_component,
            summary=summary,
            next_action=next_action,
            frontier={
                "continuity": compact_continuity_frontier(
                    gap_status,
                    selected_trade_date=selected_trade_date,
                ),
                "lake": compact_batch_frontier(
                    lake_batch,
                    selected_trade_date=selected_trade_date,
                ),
                "raw": compact_batch_frontier(
                    raw_batch,
                    selected_trade_date=selected_trade_date,
                ),
                "silver": compact_batch_frontier(
                    silver_batch,
                    selected_trade_date=selected_trade_date,
                ),
            },
            gate_statuses={"lake": compact_date_readiness(selected_status)},
            evidence={
                "expected_count": (
                    len(expected_window.expected_trade_dates) if expected_window else 0
                ),
                "registered_count": (
                    len(gap_status.registered_trade_dates) if gap_status else 0
                ),
                "max_run_requests_per_tick": 1,
                "run_attempt": run_attempt,
                "missing_source_freq_count": len(missing_source_freqs),
                "missing_source_freq": (
                    missing_source_freqs[0] if len(missing_source_freqs) == 1 else None
                ),
                "source_probe": _source_summary(source),
            },
            performance_ms={
                "lake_batch": lake_batch.elapsed_ms if lake_batch else None,
                "raw_batch": raw_batch.elapsed_ms if raw_batch else None,
                "silver_batch": silver_batch.elapsed_ms if silver_batch else None,
                "source_probe": source.elapsed_ms if source else None,
            },
        ),
    )


def _registration_skip(
    *,
    sensor_name: str,
    job_name: str,
    evaluated_at: datetime,
    expected_window: ContinuityExpectedDateWindow,
    gap_status: ContinuityRegisteredGapStatus,
) -> dg.SensorResult:
    return dg.SensorResult(
        skip_reason=(
            "主要指数分钟线专属交易日分区尚未完整注册，最早缺失日期为 "
            f"{gap_status.first_missing_registered_date}。"
        ),
        cursor=_cursor(
            sensor_name=sensor_name,
            job_name=job_name,
            evaluated_at=evaluated_at,
            expected_window=expected_window,
            gap_status=gap_status,
            selected_status=None,
            target_date=gap_status.first_missing_registered_date,
            selected_trade_date=None,
            reason_code="missing_registered_partition",
            blocked_component=cn_major_index_mins_trade_days.name,
            summary="major_index_mins waits for dedicated partition registration",
            next_action="register the first missing major_index_mins partition",
        ),
    )


def _evaluate_raw_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    sensor_name = "raw_major_index_mins_update_job_sensor"
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    try:
        duckdb_resource = context.resources.duckdb
        with duckdb_resource.connect() as connection:
            expected_window, registered, gap_status = _load_window(
                context,
                connection=connection,
                evaluated_at=evaluated_at,
            )
            if not gap_status.ready:
                return _registration_skip(
                    sensor_name=sensor_name,
                    job_name=MAJOR_INDEX_MINS_RAW_JOB_NAME,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                )
            lake_batch = batch_raw_major_index_mins_lake_readiness(
                connection=connection,
                lake_root=context.resources.lake_root.root(),
                expected_trade_dates=expected_window.expected_trade_dates,
                registered_trade_days=registered,
            )
        selection = select_first_not_ready_trade_date(
            expected_trade_dates=expected_window.expected_trade_dates,
            readiness=lake_batch,
        )
        if selection.blocked_reason == "materialized_check_failed":
            return dg.SensorResult(
                skip_reason="已存在的主要指数分钟线 Raw 分区不健康，拒绝自动覆盖。",
                cursor=_cursor(
                    sensor_name=sensor_name,
                    job_name=MAJOR_INDEX_MINS_RAW_JOB_NAME,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                    lake_batch=lake_batch,
                    selected_status=selection.selected_status,
                    target_date=selection.first_not_ready_trade_date,
                    selected_trade_date=None,
                    reason_code="materialized_check_failed",
                    blocked_component="raw_lake",
                    summary="materialized Raw core checks failed",
                    next_action="repair the existing Raw partition before retrying",
                ),
            )
        if selection.selected_trade_date is None:
            return dg.SensorResult(
                skip_reason="最近 10 个主要指数分钟线 Raw 日期均已 ready。",
                cursor=_cursor(
                    sensor_name=sensor_name,
                    job_name=MAJOR_INDEX_MINS_RAW_JOB_NAME,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                    lake_batch=lake_batch,
                    selected_status=None,
                    target_date=None,
                    selected_trade_date=None,
                    reason_code="all_ready",
                    blocked_component="none",
                    summary="recent major_index_mins Raw window is ready",
                    next_action="wait for the next expected trade date",
                ),
            )
        target_date = selection.selected_trade_date
        run_attempt = _select_raw_run_attempt(
            context.instance,
            trade_date=target_date,
        )
        if not run_attempt.can_submit:
            return dg.SensorResult(
                skip_reason=(
                    "主要指数分钟线 Raw 已有活动 run，等待其结束。"
                    if run_attempt.reason_code == "raw_run_active"
                    else "主要指数分钟线 Raw 自动重试门禁未通过，需要人工处理。"
                ),
                cursor=_cursor(
                    sensor_name=sensor_name,
                    job_name=MAJOR_INDEX_MINS_RAW_JOB_NAME,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                    lake_batch=lake_batch,
                    selected_status=selection.selected_status,
                    target_date=target_date,
                    selected_trade_date=None,
                    reason_code=run_attempt.reason_code,
                    blocked_component="raw_run_history",
                    summary="Raw run attempt guard blocks duplicate or unsafe retry",
                    next_action=(
                        "wait for the active Raw run"
                        if run_attempt.reason_code == "raw_run_active"
                        else "inspect Raw run history and repair manually"
                    ),
                ),
            )

        missing_source_freqs = _missing_raw_source_freqs(
            lake_root=context.resources.lake_root.root(),
            trade_date=target_date,
        )
        source_freq = "1min"
        if run_attempt.attempt:
            if len(missing_source_freqs) != 1:
                return dg.SensorResult(
                    skip_reason=(
                        "主要指数分钟线 Raw 自动重试只允许一个缺失频率，当前需要人工处理。"
                    ),
                    cursor=_cursor(
                        sensor_name=sensor_name,
                        job_name=MAJOR_INDEX_MINS_RAW_JOB_NAME,
                        evaluated_at=evaluated_at,
                        expected_window=expected_window,
                        gap_status=gap_status,
                        lake_batch=lake_batch,
                        selected_status=selection.selected_status,
                        target_date=target_date,
                        selected_trade_date=None,
                        reason_code="raw_retry_scope_not_single_frequency",
                        blocked_component="raw_lake",
                        summary="Raw retry scope is not one missing source frequency",
                        next_action="repair the multi-frequency gap manually",
                        run_attempt=run_attempt.attempt,
                        missing_source_freqs=missing_source_freqs,
                    ),
                )
            source_freq = missing_source_freqs[0]
        source = probe_major_index_mins_source(
            tushare=context.resources.tushare,
            trade_date=target_date,
            request_policy=_SOURCE_PROBE_POLICY,
            source_freq=source_freq,
        )
        if not source.ready:
            return dg.SensorResult(
                skip_reason="Tushare 主要指数分钟线收盘探针尚未完整返回。",
                cursor=_cursor(
                    sensor_name=sensor_name,
                    job_name=MAJOR_INDEX_MINS_RAW_JOB_NAME,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                    lake_batch=lake_batch,
                    selected_status=selection.selected_status,
                    target_date=target_date,
                    selected_trade_date=None,
                    reason_code=source.reason_code,
                    blocked_component="tushare_idx_mins_source",
                    summary=f"{source_freq} 收盘探针尚未覆盖全部日常指数",
                    next_action=f"等待 {source_freq} 源数据完整后再评估",
                    source=source,
                    run_attempt=run_attempt.attempt,
                    missing_source_freqs=missing_source_freqs,
                ),
            )
        if run_attempt.attempt == 0:
            run_request = build_run_request(
                run_key=build_asset_update_run_key(
                    subject=_RAW_RUN_SUBJECT,
                    unit_id=target_date,
                ),
                partition_key=target_date,
            )
        else:
            run_request = build_run_request(
                run_key=build_repair_attempt_run_key(
                    subject=_RAW_RUN_SUBJECT,
                    repair_scope_id=target_date,
                    attempt_scope=MAJOR_INDEX_MINS_RAW_RETRY_ATTEMPT_SCOPE,
                    attempt=run_attempt.attempt,
                ),
                partition_key=target_date,
            )
        return dg.SensorResult(
            run_requests=[run_request],
            cursor=_cursor(
                sensor_name=sensor_name,
                job_name=MAJOR_INDEX_MINS_RAW_JOB_NAME,
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                lake_batch=lake_batch,
                selected_status=selection.selected_status,
                target_date=target_date,
                selected_trade_date=target_date,
                reason_code=(
                    "request_run" if run_attempt.attempt == 0 else "request_retry_run"
                ),
                blocked_component="none",
                summary=(
                    "1min 收盘探针已齐，提交首个 Raw run"
                    if run_attempt.attempt == 0
                    else (
                        f"{source_freq} 源数据已齐，提交 Raw 第 "
                        f"{run_attempt.attempt} 次自动重试"
                    )
                ),
                next_action=(
                    "等待单分区 Raw job 完成"
                    if run_attempt.attempt == 0
                    else f"等待 {source_freq} 缺口由本次 Raw 重试补齐"
                ),
                source=source,
                run_attempt=run_attempt.attempt,
                missing_source_freqs=missing_source_freqs,
            ),
        )
    except Exception as error:  # noqa: BLE001 - sensor fails closed.
        return dg.SensorResult(
            skip_reason="主要指数分钟线 Raw sensor 执行失败，已 fail-closed。",
            cursor=_cursor(
                sensor_name=sensor_name,
                job_name=MAJOR_INDEX_MINS_RAW_JOB_NAME,
                evaluated_at=evaluated_at,
                expected_window=None,
                gap_status=None,
                selected_status=None,
                target_date=None,
                selected_trade_date=None,
                reason_code="sensor_error",
                blocked_component="sensor",
                summary="major_index_mins Raw sensor failed closed",
                next_action=f"inspect {type(error).__name__} and retry",
            ),
        )


def _evaluate_silver_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    sensor_name = "silver_major_index_mins_update_job_sensor"
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    try:
        duckdb_resource = context.resources.duckdb
        with duckdb_resource.connect() as connection:
            expected_window, registered, gap_status = _load_window(
                context,
                connection=connection,
                evaluated_at=evaluated_at,
            )
            if not gap_status.ready:
                return _registration_skip(
                    sensor_name=sensor_name,
                    job_name=MAJOR_INDEX_MINS_SILVER_JOB_NAME,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                )
            raw_batch = batch_raw_major_index_mins_lake_readiness(
                connection=connection,
                lake_root=context.resources.lake_root.root(),
                expected_trade_dates=expected_window.expected_trade_dates,
                registered_trade_days=registered,
            )
            silver_batch = batch_silver_major_index_mins_lake_readiness(
                connection=connection,
                lake_root=context.resources.lake_root.root(),
                expected_trade_dates=expected_window.expected_trade_dates,
                registered_trade_days=registered,
            )
        raw_selection = select_first_not_ready_trade_date(
            expected_trade_dates=expected_window.expected_trade_dates,
            readiness=raw_batch,
        )
        silver_selection = select_first_not_ready_trade_date(
            expected_trade_dates=expected_window.expected_trade_dates,
            readiness=silver_batch,
        )
        if silver_selection.blocked_reason == "materialized_check_failed":
            return dg.SensorResult(
                skip_reason="已存在的主要指数分钟线 Silver 分区不健康，拒绝自动覆盖。",
                cursor=_cursor(
                    sensor_name=sensor_name,
                    job_name=MAJOR_INDEX_MINS_SILVER_JOB_NAME,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                    raw_batch=raw_batch,
                    silver_batch=silver_batch,
                    selected_status=silver_selection.selected_status,
                    target_date=silver_selection.first_not_ready_trade_date,
                    selected_trade_date=None,
                    reason_code="materialized_check_failed",
                    blocked_component="silver_lake",
                    summary="materialized Silver core checks failed",
                    next_action="repair the existing Silver partition before retrying",
                ),
            )
        target_date = silver_selection.selected_trade_date
        if target_date is None:
            return dg.SensorResult(
                skip_reason="最近 10 个主要指数分钟线 Silver 日期均已 ready。",
                cursor=_cursor(
                    sensor_name=sensor_name,
                    job_name=MAJOR_INDEX_MINS_SILVER_JOB_NAME,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                    raw_batch=raw_batch,
                    silver_batch=silver_batch,
                    selected_status=None,
                    target_date=None,
                    selected_trade_date=None,
                    reason_code="all_ready",
                    blocked_component="none",
                    summary="recent major_index_mins Silver window is ready",
                    next_action="wait for the next expected trade date",
                ),
            )
        if (
            raw_selection.first_not_ready_trade_date is not None
            and raw_selection.first_not_ready_trade_date <= target_date
        ):
            return dg.SensorResult(
                skip_reason="主要指数分钟线 Raw frontier 尚未覆盖 Silver 目标日期。",
                cursor=_cursor(
                    sensor_name=sensor_name,
                    job_name=MAJOR_INDEX_MINS_SILVER_JOB_NAME,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                    raw_batch=raw_batch,
                    silver_batch=silver_batch,
                    selected_status=raw_selection.selected_status,
                    target_date=target_date,
                    selected_trade_date=None,
                    reason_code=(
                        "raw_materialized_check_failed"
                        if raw_selection.blocked_reason == "materialized_check_failed"
                        else "raw_not_ready"
                    ),
                    blocked_component="raw_lake",
                    summary="Raw must be ready before the Silver target date",
                    next_action="wait for the Raw sensor to close the upstream date",
                ),
            )
        return dg.SensorResult(
            run_requests=[
                build_run_request(
                    run_key=build_asset_update_run_key(
                        subject=MAJOR_INDEX_MINS_SILVER_JOB_NAME.removesuffix("_job"),
                        unit_id=target_date,
                    ),
                    partition_key=target_date,
                )
            ],
            cursor=_cursor(
                sensor_name=sensor_name,
                job_name=MAJOR_INDEX_MINS_SILVER_JOB_NAME,
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                raw_batch=raw_batch,
                silver_batch=silver_batch,
                selected_status=silver_selection.selected_status,
                target_date=target_date,
                selected_trade_date=target_date,
                reason_code="request_run",
                blocked_component="none",
                summary="Raw frontier is ready; request the first Silver gap",
                next_action="run the single-partition Silver job",
            ),
        )
    except Exception as error:  # noqa: BLE001 - sensor fails closed.
        return dg.SensorResult(
            skip_reason="主要指数分钟线 Silver sensor 执行失败，已 fail-closed。",
            cursor=_cursor(
                sensor_name=sensor_name,
                job_name=MAJOR_INDEX_MINS_SILVER_JOB_NAME,
                evaluated_at=evaluated_at,
                expected_window=None,
                gap_status=None,
                selected_status=None,
                target_date=None,
                selected_trade_date=None,
                reason_code="sensor_error",
                blocked_component="sensor",
                summary="major_index_mins Silver sensor failed closed",
                next_action=f"inspect {type(error).__name__} and retry",
            ),
        )


@dg.sensor(
    job_name=MAJOR_INDEX_MINS_RAW_JOB_NAME,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb", "tushare"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="最近 10 个专属日期内，Tushare 收盘探针 ready 后提交一个 Raw 分区。",
)
def raw_major_index_mins_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return _evaluate_raw_sensor(context)


@dg.sensor(
    job_name=MAJOR_INDEX_MINS_SILVER_JOB_NAME,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="Raw 最近 10 日 ready 后，提交一个 Silver 主要指数分钟线分区。",
)
def silver_major_index_mins_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return _evaluate_silver_sensor(context)


__all__ = [
    "raw_major_index_mins_update_job_sensor",
    "silver_major_index_mins_update_job_sensor",
]
