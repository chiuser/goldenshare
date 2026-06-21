from datetime import datetime

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    DEFAULT_CONTINUITY_WINDOW_LIMIT,
    ContinuityExpectedDateWindow,
    ContinuityRegisteredGapStatus,
    build_continuity_cursor_details,
    build_registered_gap_status,
    load_expected_trade_date_window,
)
from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.paths import silver_index_basic_path, silver_trade_calendar_path
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
from orchestrator.defs.sensors.index_daily_raw_file_readiness import (
    MAX_RAW_GAP_SAMPLE_COUNT,
    RAW_GAP_AUDIT_TRADE_DAY_LIMIT,
    IndexDailyRawGapAudit,
    IndexDailyRawFileReadiness,
    audit_index_daily_raw_gaps,
    check_index_daily_raw_files_for_trade_date,
)
from orchestrator.defs.sensors.cn_a_trade_day_sensor import (
    INDEX_TRADE_DAY_MIN_DATE,
    SAME_DAY_PARTITION_REGISTER_START,
)
from orchestrator.defs.sensors.readiness import (
    AssetReadinessStatus,
    CN_A_SENSOR_TIMEZONE,
    select_first_not_ready_silver_index_daily_partition,
)


MAX_STATUS_SAMPLE_COUNT = 20


def _asset_status_payload(status: AssetReadinessStatus) -> dict[str, object]:
    return {
        "asset_key": status.asset_key,
        "partition_key": status.partition_key,
        "ready": status.ready,
        "materialized": status.materialized,
        "checks_passed": status.checks_passed,
        "freshness_passed": status.freshness_passed,
        "materialization_storage_id": status.materialization_storage_id,
        "materialization_date": status.materialization_date,
        "missing_check_names": list(status.missing_check_names),
        "failed_check_names": list(status.failed_check_names),
        "reason": status.reason,
    }


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
    gap_status: ContinuityRegisteredGapStatus,
) -> str:
    return (
        "指数交易日分区存在缺口，最早缺失日期为 "
        f"{gap_status.first_missing_registered_date}，暂不触发指数日线 silver 更新。"
    )


def _recent_trade_dates(
    trade_dates: tuple[str, ...],
    *,
    limit: int = RAW_GAP_AUDIT_TRADE_DAY_LIMIT,
) -> tuple[str, ...]:
    if limit <= 0:
        raise ValueError("limit must be positive.")
    return trade_dates[-limit:]


def _first_not_ready_silver_trade_date(
    instance: dg.DagsterInstance,
    trade_dates: tuple[str, ...],
) -> tuple[str | None, AssetReadinessStatus | None]:
    return select_first_not_ready_silver_index_daily_partition(instance, trade_dates)


def _cursor_payload(
    *,
    evaluated_at: datetime,
    target_trade_date: str | None,
    registered_trade_day_count: int,
    registered_code_count: int,
    raw_ready_code_count: int,
    missing_raw_file_count: int,
    missing_raw_trade_date_count: int,
    selected_trade_date: str | None,
    silver_status: AssetReadinessStatus | None,
    missing_raw_file_samples: tuple[str, ...],
    missing_raw_trade_date_samples: tuple[str, ...],
    raw_scan_error_code: str | None = None,
    raw_scan_error: str | None = None,
    no_raw_history_count: int = 0,
    no_raw_history_samples: tuple[str, ...] = (),
    continuity_details: dict[str, object] | None = None,
) -> str:
    decision = (
        SensorCursorDecision.REQUEST_RUNS
        if selected_trade_date
        else SensorCursorDecision.SKIP
    )
    blocked_count = missing_raw_file_count + missing_raw_trade_date_count
    if raw_scan_error:
        blocked_count = max(blocked_count, registered_code_count)
    sample_keys = (
        missing_raw_file_samples
        or missing_raw_trade_date_samples
        or ((selected_trade_date,) if selected_trade_date else ())
    )
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_trade_date,
        selected_count=1 if selected_trade_date else 0,
        blocked_count=blocked_count,
        sample_keys=sample_keys,
        details={
            "registered_trade_day_count": registered_trade_day_count,
            "registered_code_count": registered_code_count,
            "raw_ready_code_count": raw_ready_code_count,
            "missing_raw_file_count": missing_raw_file_count,
            "missing_raw_trade_date_count": missing_raw_trade_date_count,
            "selected_trade_date": selected_trade_date,
            "silver_status": _asset_status_payload(silver_status)
            if silver_status
            else None,
            "missing_raw_file_samples": list(missing_raw_file_samples),
            "missing_raw_trade_date_samples": list(missing_raw_trade_date_samples),
            "raw_scan_error_code": raw_scan_error_code,
            "raw_scan_error": raw_scan_error,
            "no_raw_history_count": no_raw_history_count,
            "no_raw_history_samples": list(no_raw_history_samples),
            "continuity_status": continuity_details,
        },
    )


def _raw_file_readiness_cursor_fields(
    raw_status: IndexDailyRawFileReadiness | None,
) -> dict[str, object]:
    if raw_status is None:
        return {
            "raw_ready_code_count": 0,
            "missing_raw_file_count": 0,
            "missing_raw_trade_date_count": 0,
            "missing_raw_file_samples": (),
            "missing_raw_trade_date_samples": (),
            "raw_scan_error_code": None,
            "raw_scan_error": None,
            "no_raw_history_count": 0,
            "no_raw_history_samples": (),
        }
    return {
        "raw_ready_code_count": raw_status.ready_code_count,
        "missing_raw_file_count": raw_status.missing_file_count,
        "missing_raw_trade_date_count": raw_status.missing_trade_date_count,
        "missing_raw_file_samples": raw_status.missing_file_codes[:MAX_STATUS_SAMPLE_COUNT],
        "missing_raw_trade_date_samples": raw_status.missing_trade_date_codes[
            :MAX_STATUS_SAMPLE_COUNT
        ],
        "raw_scan_error_code": raw_status.scan_error_code,
        "raw_scan_error": raw_status.scan_error,
        "no_raw_history_count": 0,
        "no_raw_history_samples": (),
    }


def _raw_gap_audit_cursor_fields(
    raw_gap_audit: IndexDailyRawGapAudit | None,
) -> dict[str, object]:
    if raw_gap_audit is None:
        return _raw_file_readiness_cursor_fields(None)
    return {
        "raw_ready_code_count": raw_gap_audit.ready_pair_count,
        "missing_raw_file_count": raw_gap_audit.missing_file_count,
        "missing_raw_trade_date_count": raw_gap_audit.missing_trade_date_pair_count,
        "missing_raw_file_samples": raw_gap_audit.missing_file_codes[
            :MAX_STATUS_SAMPLE_COUNT
        ],
        "missing_raw_trade_date_samples": tuple(
            f"{trade_date}:{ts_code}"
            for trade_date, ts_code in raw_gap_audit.missing_pair_samples[
                :MAX_STATUS_SAMPLE_COUNT
            ]
        ),
        "raw_scan_error_code": raw_gap_audit.scan_error_code,
        "raw_scan_error": raw_gap_audit.scan_error,
        "no_raw_history_count": raw_gap_audit.no_raw_history_count,
        "no_raw_history_samples": raw_gap_audit.no_raw_history_codes[
            :MAX_STATUS_SAMPLE_COUNT
        ],
    }


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
    description="指数日线 raw-by-code 文件包含目标交易日数据后，触发 silver 分区生成任务。",
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
    continuity_details = _continuity_details(
        expected_window=expected_window,
        gap_status=gap_status,
    )
    if gap_status.first_missing_registered_date is not None:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=gap_status.first_missing_registered_date,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            silver_status=None,
            continuity_details=continuity_details,
            **_raw_file_readiness_cursor_fields(None),
        )
        return dg.SensorResult(
            skip_reason=_registered_gap_skip_reason(gap_status),
            cursor=cursor,
        )

    if not registered_trade_days:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=None,
            registered_trade_day_count=0,
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            silver_status=None,
            continuity_details=continuity_details,
            **_raw_file_readiness_cursor_fields(None),
        )
        return dg.SensorResult(
            skip_reason="没有注册指数交易日分区，无法触发指数日线 silver 生成。",
            cursor=cursor,
        )

    if not registered_index_codes:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=None,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=0,
            selected_trade_date=None,
            silver_status=None,
            continuity_details=continuity_details,
            **_raw_file_readiness_cursor_fields(None),
        )
        return dg.SensorResult(
            skip_reason="没有注册指数代码分区，无法触发指数日线 silver 生成。",
            cursor=cursor,
        )

    eligible_trade_dates = _recent_trade_dates(expected_window.expected_trade_dates)
    if not eligible_trade_dates:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=None,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            silver_status=None,
            continuity_details=continuity_details,
            **_raw_file_readiness_cursor_fields(None),
        )
        return dg.SensorResult(
            skip_reason="没有符合当前日期窗口的指数交易日分区。",
            cursor=cursor,
        )

    raw_gap_audit = audit_index_daily_raw_gaps(
        lake_root_path=context.resources.lake_root.root(),
        duckdb=context.resources.duckdb,
        registered_index_codes=registered_index_codes,
        trade_dates=eligible_trade_dates,
        index_basic_path=silver_index_basic_path(context.resources.lake_root.root()),
        sample_limit=MAX_RAW_GAP_SAMPLE_COUNT,
    )
    if raw_gap_audit.scan_error:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=raw_gap_audit.first_missing_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            silver_status=None,
            continuity_details=continuity_details,
            **_raw_gap_audit_cursor_fields(raw_gap_audit),
        )
        return dg.SensorResult(
            skip_reason="指数日线 raw gap audit 扫描失败，暂不生成 silver。",
            cursor=cursor,
        )
    if not raw_gap_audit.ready:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=raw_gap_audit.first_missing_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            silver_status=None,
            continuity_details=continuity_details,
            **_raw_gap_audit_cursor_fields(raw_gap_audit),
        )
        return dg.SensorResult(
            skip_reason=(
                "最近 60 个可运行指数交易日内 raw-by-code 仍存在有效空洞，"
                "暂不生成 silver。"
            ),
            cursor=cursor,
        )

    target_trade_date, silver_status = _first_not_ready_silver_trade_date(
        context.instance,
        eligible_trade_dates,
    )
    if target_trade_date is None or silver_status is None:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=None,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            silver_status=None,
            raw_ready_code_count=raw_gap_audit.ready_pair_count,
            missing_raw_file_count=0,
            missing_raw_trade_date_count=0,
            missing_raw_file_samples=(),
            missing_raw_trade_date_samples=(),
            no_raw_history_count=raw_gap_audit.no_raw_history_count,
            no_raw_history_samples=raw_gap_audit.no_raw_history_codes[
                :MAX_STATUS_SAMPLE_COUNT
            ],
            continuity_details=continuity_details,
        )
        return dg.SensorResult(
            skip_reason="最近 60 个可运行指数交易日的 silver_index_daily 分区都已经 ready。",
            cursor=cursor,
        )

    if silver_status.materialized:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            selected_trade_date=None,
            silver_status=silver_status,
            continuity_details=continuity_details,
            **_raw_file_readiness_cursor_fields(None),
        )
        return dg.SensorResult(
            skip_reason=(
                "目标指数交易日的 silver_index_daily 已生成但 blocking checks 未全绿，"
                "暂不自动重跑，请先人工处理失败检查。"
            ),
            cursor=cursor,
        )

    raw_status = check_index_daily_raw_files_for_trade_date(
        lake_root_path=context.resources.lake_root.root(),
        duckdb=context.resources.duckdb,
        registered_index_codes=registered_index_codes,
        trade_date=target_trade_date,
        index_basic_path=silver_index_basic_path(context.resources.lake_root.root()),
    )
    cursor = _cursor_payload(
        evaluated_at=evaluated_at,
        target_trade_date=target_trade_date,
        registered_trade_day_count=len(registered_trade_days),
        registered_code_count=len(registered_index_codes),
        selected_trade_date=target_trade_date if raw_status.ready else None,
        silver_status=silver_status,
        continuity_details=continuity_details,
        **_raw_file_readiness_cursor_fields(raw_status),
    )

    if not raw_status.ready:
        if raw_status.scan_error:
            context.log.warning(
                "index_daily_raw_file_readiness_scan_failed trade_date=%s "
                "error_code=%s error=%s",
                target_trade_date,
                raw_status.scan_error_code,
                raw_status.scan_error,
            )
            skip_reason = "指数日线 raw 文件扫描失败，暂不生成 silver。"
        elif raw_status.missing_file_count:
            skip_reason = "指数日线 raw-by-code 文件仍有缺失代码，暂不生成 silver。"
        else:
            skip_reason = "指数日线 raw-by-code 文件仍有代码缺少目标交易日数据，暂不生成 silver。"
        return dg.SensorResult(
            skip_reason=skip_reason,
            cursor=cursor,
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
        cursor=cursor,
    )
