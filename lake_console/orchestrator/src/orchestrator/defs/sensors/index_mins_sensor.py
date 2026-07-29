"""Bounded Raw/Silver sensors for index minute partitions."""

from datetime import datetime

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityBatchReadiness,
    ContinuityExpectedDateWindow,
    ContinuityRegisteredGapStatus,
    build_registered_gap_status,
    load_expected_trade_date_window,
    select_first_not_ready_trade_date,
)
from orchestrator.defs.asset_guards.index_mins_lake_readiness import (
    batch_raw_index_mins_lake_readiness,
    batch_silver_index_mins_lake_readiness,
)
from orchestrator.defs.partitions import cn_a_index_mins_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.prod_db.index_mins import (
    IndexMinsActivePool,
    ProdIndexMinsSourceReadiness,
    load_prod_index_mins_active_pool,
    probe_prod_index_mins_source,
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
from orchestrator.defs.run_contracts.index_mins import INDEX_MINS_HISTORY_START_DATE
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE


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
        min_trade_date=INDEX_MINS_HISTORY_START_DATE,
        same_day_register_start=None,
        window_limit=10,
    )
    registered = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_index_mins_trade_days.name))
    )
    gap_status = build_registered_gap_status(
        expected_trade_dates=expected_window.expected_trade_dates,
        registered_trade_dates=registered,
    )
    return expected_window, registered, gap_status


def _source_summary(
    source: ProdIndexMinsSourceReadiness | None,
    active_pool: IndexMinsActivePool | None,
) -> dict[str, object] | None:
    if source is None:
        return None
    return {
        "ready": source.ready,
        "reason_code": source.reason_code,
        "expected_code_count": source.expected_code_count,
        "expected_code_set_hash": source.expected_code_set_hash,
        "frequency_count": len(source.frequency_coverages),
        "empty_frequency_count": sum(
            item.source_row_count <= 0 for item in source.frequency_coverages
        ),
        "incomplete_frequency_count": sum(
            item.returned_code_count != item.expected_code_count
            for item in source.frequency_coverages
        ),
        "duplicate_key_count": sum(
            item.duplicate_key_count for item in source.frequency_coverages
        ),
        "active_pool_count": active_pool.code_count if active_pool else None,
        "active_pool_hash": active_pool.code_set_hash if active_pool else None,
        "elapsed_ms": source.elapsed_ms,
        "query_count": len(source.frequency_coverages),
    }


def _cursor(
    *,
    sensor_name: str,
    job_name: str,
    evaluated_at: datetime,
    expected_window: ContinuityExpectedDateWindow | None,
    gap_status: ContinuityRegisteredGapStatus | None,
    lake_batch: ContinuityBatchReadiness | None,
    selected_status: object | None,
    target_date: str | None,
    selected_trade_date: str | None,
    reason_code: str,
    blocked_component: str,
    summary: str,
    next_action: str,
    source: ProdIndexMinsSourceReadiness | None = None,
    active_pool: IndexMinsActivePool | None = None,
    raw_batch: ContinuityBatchReadiness | None = None,
    silver_batch: ContinuityBatchReadiness | None = None,
) -> str:
    expected_count = len(expected_window.expected_trade_dates) if expected_window else 0
    registered_count = len(gap_status.registered_trade_dates) if gap_status else 0
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
            asset_family="index_mins",
            partition_set=cn_a_index_mins_trade_days.name,
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
                "expected_count": expected_count,
                "registered_count": registered_count,
                "max_run_requests_per_tick": 1,
                "source_probe": _source_summary(source, active_pool),
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
            "指数分钟线专属交易日分区尚未完整注册，最早缺失日期为 "
            f"{gap_status.first_missing_registered_date}。"
        ),
        cursor=_cursor(
            sensor_name=sensor_name,
            job_name=job_name,
            evaluated_at=evaluated_at,
            expected_window=expected_window,
            gap_status=gap_status,
            lake_batch=None,
            selected_status=None,
            target_date=gap_status.first_missing_registered_date,
            selected_trade_date=None,
            reason_code="missing_registered_partition",
            blocked_component=cn_a_index_mins_trade_days.name,
            summary="index_mins waits for dedicated trade-date partition registration",
            next_action="register the first missing index_mins trade-date partition",
        ),
    )


def _evaluate_raw_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    sensor_name = "raw_index_mins_update_job_sensor"
    job_name = "raw_index_mins_update_job"
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
                    job_name=job_name,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                )
            lake_batch = batch_raw_index_mins_lake_readiness(
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
                skip_reason="已存在的指数分钟线 Raw 分区 core check 失败，拒绝自动覆盖。",
                cursor=_cursor(
                    sensor_name=sensor_name,
                    job_name=job_name,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                    lake_batch=lake_batch,
                    selected_status=selection.selected_status,
                    target_date=selection.first_not_ready_trade_date,
                    selected_trade_date=None,
                    reason_code="materialized_check_failed",
                    blocked_component="raw_lake",
                    summary="materialized Raw core checks failed; no automatic overwrite",
                    next_action="repair the existing Raw partition before retrying",
                ),
            )
        if selection.selected_trade_date is None:
            return dg.SensorResult(
                skip_reason="最近 10 个指数分钟线 Raw expected 日期均已 ready。",
                cursor=_cursor(
                    sensor_name=sensor_name,
                    job_name=job_name,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                    lake_batch=lake_batch,
                    selected_status=None,
                    target_date=None,
                    selected_trade_date=None,
                    reason_code="all_ready",
                    blocked_component="none",
                    summary="recent index_mins Raw window is ready",
                    next_action="wait for the next expected trade date",
                ),
            )

        active_pool = load_prod_index_mins_active_pool(
            prod_postgres=context.resources.prod_postgres,
        )
        source = probe_prod_index_mins_source(
            prod_postgres=context.resources.prod_postgres,
            trade_date=selection.selected_trade_date,
            effective_codes=active_pool.codes,
        )
        if not source.ready:
            return dg.SensorResult(
                skip_reason="Prod 指数分钟线源尚未满足五频完整性门禁。",
                cursor=_cursor(
                    sensor_name=sensor_name,
                    job_name=job_name,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                    lake_batch=lake_batch,
                    selected_status=selection.selected_status,
                    target_date=selection.selected_trade_date,
                    selected_trade_date=None,
                    reason_code=source.reason_code,
                    blocked_component="prod_index_mins_source",
                    summary="Prod source coverage is not ready for the first Raw gap",
                    next_action="wait for all five source frequencies to close",
                    source=source,
                    active_pool=active_pool,
                ),
            )
        target_date = selection.selected_trade_date
        return dg.SensorResult(
            run_requests=[
                build_run_request(
                    run_key=build_asset_update_run_key(
                        subject=job_name.removesuffix("_job"),
                        unit_id=target_date,
                    ),
                    partition_key=target_date,
                )
            ],
            cursor=_cursor(
                sensor_name=sensor_name,
                job_name=job_name,
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                lake_batch=lake_batch,
                selected_status=selection.selected_status,
                target_date=target_date,
                selected_trade_date=target_date,
                reason_code="request_run",
                blocked_component="none",
                summary="Prod source coverage is ready; request the first Raw gap",
                next_action="run the single-partition Raw job",
                source=source,
                active_pool=active_pool,
            ),
        )
    except Exception as error:  # noqa: BLE001 - sensor must fail closed.
        return dg.SensorResult(
            skip_reason="指数分钟线 Raw sensor 执行失败，已 fail-closed。",
            cursor=_cursor(
                sensor_name=sensor_name,
                job_name=job_name,
                evaluated_at=evaluated_at,
                expected_window=None,
                gap_status=None,
                lake_batch=None,
                selected_status=None,
                target_date=None,
                selected_trade_date=None,
                reason_code="sensor_error",
                blocked_component="sensor",
                summary="index_mins Raw sensor failed closed",
                next_action=f"inspect {type(error).__name__} and retry",
            ),
        )


def _evaluate_silver_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    sensor_name = "silver_index_mins_update_job_sensor"
    job_name = "silver_index_mins_update_job"
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
                    job_name=job_name,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                )
            raw_batch = batch_raw_index_mins_lake_readiness(
                connection=connection,
                lake_root=context.resources.lake_root.root(),
                expected_trade_dates=expected_window.expected_trade_dates,
                registered_trade_days=registered,
            )
            silver_batch = batch_silver_index_mins_lake_readiness(
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
                skip_reason="已存在的指数分钟线 Silver 分区 core check 失败，拒绝自动覆盖。",
                cursor=_cursor(
                    sensor_name=sensor_name,
                    job_name=job_name,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                    lake_batch=silver_batch,
                    selected_status=silver_selection.selected_status,
                    target_date=silver_selection.first_not_ready_trade_date,
                    selected_trade_date=None,
                    reason_code="materialized_check_failed",
                    blocked_component="silver_lake",
                    summary="materialized Silver core checks failed; no automatic overwrite",
                    next_action="repair the existing Silver partition before retrying",
                    raw_batch=raw_batch,
                    silver_batch=silver_batch,
                ),
            )
        target_date = silver_selection.selected_trade_date
        if target_date is None:
            return dg.SensorResult(
                skip_reason="最近 10 个指数分钟线 Silver expected 日期均已 ready。",
                cursor=_cursor(
                    sensor_name=sensor_name,
                    job_name=job_name,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                    lake_batch=silver_batch,
                    selected_status=None,
                    target_date=None,
                    selected_trade_date=None,
                    reason_code="all_ready",
                    blocked_component="none",
                    summary="recent index_mins Silver window is ready",
                    next_action="wait for the next expected trade date",
                    raw_batch=raw_batch,
                    silver_batch=silver_batch,
                ),
            )
        if (
            raw_selection.first_not_ready_trade_date is not None
            and raw_selection.first_not_ready_trade_date <= target_date
        ):
            return dg.SensorResult(
                skip_reason="指数分钟线 Raw frontier 尚未覆盖 Silver 目标日期。",
                cursor=_cursor(
                    sensor_name=sensor_name,
                    job_name=job_name,
                    evaluated_at=evaluated_at,
                    expected_window=expected_window,
                    gap_status=gap_status,
                    lake_batch=raw_batch,
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
                    raw_batch=raw_batch,
                    silver_batch=silver_batch,
                ),
            )
        return dg.SensorResult(
            run_requests=[
                build_run_request(
                    run_key=build_asset_update_run_key(
                        subject=job_name.removesuffix("_job"),
                        unit_id=target_date,
                    ),
                    partition_key=target_date,
                )
            ],
            cursor=_cursor(
                sensor_name=sensor_name,
                job_name=job_name,
                evaluated_at=evaluated_at,
                expected_window=expected_window,
                gap_status=gap_status,
                lake_batch=silver_batch,
                selected_status=silver_selection.selected_status,
                target_date=target_date,
                selected_trade_date=target_date,
                reason_code="request_run",
                blocked_component="none",
                summary="Raw frontier is ready; request the first Silver gap",
                next_action="run the single-partition Silver job",
                raw_batch=raw_batch,
                silver_batch=silver_batch,
            ),
        )
    except Exception as error:  # noqa: BLE001 - sensor must fail closed.
        return dg.SensorResult(
            skip_reason="指数分钟线 Silver sensor 执行失败，已 fail-closed。",
            cursor=_cursor(
                sensor_name=sensor_name,
                job_name=job_name,
                evaluated_at=evaluated_at,
                expected_window=None,
                gap_status=None,
                lake_batch=None,
                selected_status=None,
                target_date=None,
                selected_trade_date=None,
                reason_code="sensor_error",
                blocked_component="sensor",
                summary="index_mins Silver sensor failed closed",
                next_action=f"inspect {type(error).__name__} and retry",
            ),
        )


@dg.sensor(
    job_name="raw_index_mins_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb", "prod_postgres"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="最近 10 个专属日期内，Prod 五频 ready 后提交一个 Raw 指数分钟线分区。",
)
def raw_index_mins_update_job_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    return _evaluate_raw_sensor(context)


@dg.sensor(
    job_name="silver_index_mins_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="Raw 最近 10 日 ready 后，提交一个 Silver 指数分钟线分区。",
)
def silver_index_mins_update_job_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    return _evaluate_silver_sensor(context)


__all__ = [
    "raw_index_mins_update_job_sensor",
    "silver_index_mins_update_job_sensor",
]
