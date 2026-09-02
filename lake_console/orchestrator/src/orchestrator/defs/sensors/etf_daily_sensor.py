"""Stopped-by-default daily update sensors for ETF daily lake datasets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    build_registered_gap_status,
    load_expected_trade_date_window,
)
from orchestrator.defs.asset_guards.etf_basic_readiness import (
    select_latest_etf_basic_snapshot_reference,
)
from orchestrator.defs.asset_guards.etf_daily_lake_readiness import (
    EtfDailyBatchReadiness,
    EtfDailyPartitionReadiness,
    batch_etf_adj_factor_silver_lake_readiness,
    batch_etf_daily_silver_lake_readiness,
    batch_fund_adj_raw_lake_readiness,
    batch_fund_daily_raw_lake_readiness,
)
from orchestrator.defs.asset_guards.etf_daily_source_probe import (
    EtfDailySourcePublication,
    probe_fund_adj_publication,
    probe_fund_daily_publication,
)
from orchestrator.defs.jobs.etf_daily import (
    raw_fund_adj_update_job,
    raw_fund_daily_update_job,
    silver_etf_adj_factor_update_job,
    silver_etf_daily_update_job,
)
from orchestrator.defs.partitions import cn_a_etf_mins_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursor_payloads import build_cursor_details
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.etf_daily import (
    ETF_DAILY_AUTOMATION_CONTRACT_REVISION,
    ETF_DAILY_BOOTSTRAP_START_DATE,
    ETF_DAILY_SENSOR_WINDOW_LIMIT,
    RAW_FUND_ADJ_JOB_NAME,
    RAW_FUND_ADJ_SENSOR_NAME,
    RAW_FUND_DAILY_JOB_NAME,
    RAW_FUND_DAILY_SENSOR_NAME,
    SILVER_ETF_ADJ_FACTOR_JOB_NAME,
    SILVER_ETF_ADJ_FACTOR_SENSOR_NAME,
    SILVER_ETF_DAILY_JOB_NAME,
    SILVER_ETF_DAILY_SENSOR_NAME,
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

_RUN_START = time(21, 0)
_PARTITION_SET_NAME = cn_a_etf_mins_trade_days.name


@dataclass(frozen=True, slots=True)
class _RawSensorSpec:
    sensor_name: str
    job_name: str
    asset_family: str
    readiness: Callable[..., EtfDailyBatchReadiness]
    publication_probe: Callable[..., EtfDailySourcePublication]


@dataclass(frozen=True, slots=True)
class _SilverSensorSpec:
    sensor_name: str
    job_name: str
    asset_family: str
    raw_readiness: Callable[..., EtfDailyBatchReadiness]
    silver_readiness: Callable[..., EtfDailyBatchReadiness]


_RAW_FUND_DAILY_SPEC = _RawSensorSpec(
    sensor_name=RAW_FUND_DAILY_SENSOR_NAME,
    job_name=RAW_FUND_DAILY_JOB_NAME,
    asset_family="fund_daily",
    readiness=batch_fund_daily_raw_lake_readiness,
    publication_probe=probe_fund_daily_publication,
)
_RAW_FUND_ADJ_SPEC = _RawSensorSpec(
    sensor_name=RAW_FUND_ADJ_SENSOR_NAME,
    job_name=RAW_FUND_ADJ_JOB_NAME,
    asset_family="fund_adj",
    readiness=batch_fund_adj_raw_lake_readiness,
    publication_probe=probe_fund_adj_publication,
)
_SILVER_ETF_DAILY_SPEC = _SilverSensorSpec(
    sensor_name=SILVER_ETF_DAILY_SENSOR_NAME,
    job_name=SILVER_ETF_DAILY_JOB_NAME,
    asset_family="etf_daily",
    raw_readiness=batch_fund_daily_raw_lake_readiness,
    silver_readiness=batch_etf_daily_silver_lake_readiness,
)
_SILVER_ETF_ADJ_FACTOR_SPEC = _SilverSensorSpec(
    sensor_name=SILVER_ETF_ADJ_FACTOR_SENSOR_NAME,
    job_name=SILVER_ETF_ADJ_FACTOR_JOB_NAME,
    asset_family="etf_adj_factor",
    raw_readiness=batch_fund_adj_raw_lake_readiness,
    silver_readiness=batch_etf_adj_factor_silver_lake_readiness,
)


def _normalize_evaluated_at(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=CN_A_SENSOR_TIMEZONE)
    return value.astimezone(CN_A_SENSOR_TIMEZONE)


def _compact_status(
    status: EtfDailyPartitionReadiness | None,
) -> dict[str, object] | None:
    if status is None:
        return None
    return {
        "asset_key": status.asset_key,
        "trade_date": status.trade_date,
        "ready": status.ready,
        "materialized": status.materialized,
        "file_exists": status.file_exists,
        "checks_passed": status.checks_passed,
        "reason_code": status.reason_code,
        "row_count": status.row_count,
        "content_hash": status.content_hash,
    }


def _cursor(
    *,
    evaluated_at: datetime,
    sensor_name: str,
    job_name: str,
    asset_family: str,
    decision: SensorCursorDecision,
    reason_code: str,
    summary: str,
    next_action: str,
    blocked_component: str | None = None,
    target_date: str | None = None,
    window_dates: tuple[str, ...] = (),
    raw_status: EtfDailyPartitionReadiness | None = None,
    silver_status: EtfDailyPartitionReadiness | None = None,
    publication: EtfDailySourcePublication | None = None,
    basic_fingerprint: str | None = None,
    raw_batch: EtfDailyBatchReadiness | None = None,
    silver_batch: EtfDailyBatchReadiness | None = None,
) -> str:
    selected = decision is SensorCursorDecision.REQUEST_RUNS
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=decision,
        target_date=target_date,
        selected_count=1 if selected else 0,
        blocked_count=0 if selected else (1 if blocked_component else 0),
        sample_keys=(target_date,) if selected and target_date else (),
        details=build_cursor_details(
            sensor_name=sensor_name,
            job_name=job_name,
            asset_family=asset_family,
            partition_set=_PARTITION_SET_NAME,
            reason_code=reason_code,
            blocked_component=blocked_component,
            summary=summary,
            next_action=next_action,
            frontier={
                "window_start": window_dates[0] if window_dates else None,
                "window_end": window_dates[-1] if window_dates else None,
                "window_count": len(window_dates),
                "earliest_gap": target_date,
            },
            gate_statuses={
                "raw": _compact_status(raw_status),
                "silver": _compact_status(silver_status),
                "publication": (
                    {
                        "ready": publication.ready,
                        "reason_code": publication.reason_code,
                        "row_count": publication.row_count,
                    }
                    if publication is not None
                    else None
                ),
                "basic": (
                    {"reference_fingerprint": basic_fingerprint}
                    if basic_fingerprint is not None
                    else None
                ),
            },
            runtime_state={
                "window_limit": ETF_DAILY_SENSOR_WINDOW_LIMIT,
                "contract_revision": ETF_DAILY_AUTOMATION_CONTRACT_REVISION,
                "materialization_query_count": sum(
                    batch.materialization_query_count
                    for batch in (raw_batch, silver_batch)
                    if batch is not None
                ),
            },
            performance_ms={
                "raw_readiness": raw_batch.elapsed_ms if raw_batch else None,
                "silver_readiness": silver_batch.elapsed_ms if silver_batch else None,
                "publication_probe": (
                    publication.elapsed_ms if publication is not None else None
                ),
            },
        ),
    )


def _skip(
    *,
    evaluated_at: datetime,
    sensor_name: str,
    job_name: str,
    asset_family: str,
    reason_code: str,
    message: str,
    blocked_component: str | None = None,
    target_date: str | None = None,
    window_dates: tuple[str, ...] = (),
    raw_status: EtfDailyPartitionReadiness | None = None,
    silver_status: EtfDailyPartitionReadiness | None = None,
    publication: EtfDailySourcePublication | None = None,
    raw_batch: EtfDailyBatchReadiness | None = None,
    silver_batch: EtfDailyBatchReadiness | None = None,
) -> dg.SensorResult:
    return dg.SensorResult(
        skip_reason=message,
        cursor=_cursor(
            evaluated_at=evaluated_at,
            sensor_name=sensor_name,
            job_name=job_name,
            asset_family=asset_family,
            decision=SensorCursorDecision.SKIP,
            reason_code=reason_code,
            summary=f"ETF daily sensor skipped: {reason_code}",
            next_action="wait for or repair the blocking condition",
            blocked_component=blocked_component,
            target_date=target_date,
            window_dates=window_dates,
            raw_status=raw_status,
            silver_status=silver_status,
            publication=publication,
            raw_batch=raw_batch,
            silver_batch=silver_batch,
        ),
    )


def _window_and_registration(
    context: dg.SensorEvaluationContext,
    *,
    connection: Any,
    evaluated_at: datetime,
):
    window = load_expected_trade_date_window(
        connection,
        silver_trade_calendar_path(context.resources.lake_root.root()),
        evaluated_at=evaluated_at,
        min_trade_date=ETF_DAILY_BOOTSTRAP_START_DATE.isoformat(),
        same_day_register_start=_RUN_START,
        window_limit=ETF_DAILY_SENSOR_WINDOW_LIMIT,
    )
    registered = tuple(
        sorted(context.instance.get_dynamic_partitions(_PARTITION_SET_NAME))
    )
    gap = build_registered_gap_status(
        expected_trade_dates=window.expected_trade_dates,
        registered_trade_dates=registered,
    )
    return window, gap


def _first_raw_decision(
    batch: EtfDailyBatchReadiness,
) -> tuple[str, EtfDailyPartitionReadiness | None]:
    for status in batch.statuses:
        if status.ready:
            continue
        if status.materialized or status.file_exists:
            return "existing_invalid", status
        return "missing", status
    return "all_ready", None


def _evaluate_raw(
    context: dg.SensorEvaluationContext,
    *,
    spec: _RawSensorSpec,
    evaluated_at: datetime | None,
) -> dg.SensorResult:
    now = _normalize_evaluated_at(
        evaluated_at or datetime.now(CN_A_SENSOR_TIMEZONE)
    )
    if now.time() < _RUN_START:
        return _skip(
            evaluated_at=now,
            sensor_name=spec.sensor_name,
            job_name=spec.job_name,
            asset_family=spec.asset_family,
            reason_code="outside_operating_window",
            message="ETF 日频自动更新等待上海时间 21:00 运行窗口。",
        )
    try:
        context.resources.lake_root.ensure_available_for_run()
        with context.resources.duckdb.connect() as connection:
            window, gap = _window_and_registration(
                context,
                connection=connection,
                evaluated_at=now,
            )
            dates = window.expected_trade_dates
            if not dates:
                return _skip(
                    evaluated_at=now,
                    sensor_name=spec.sensor_name,
                    job_name=spec.job_name,
                    asset_family=spec.asset_family,
                    reason_code="expected_window_empty",
                    message="ETF 共享交易日历当前没有可评估日期。",
                    blocked_component="trade_calendar",
                )
            if not gap.ready:
                return _skip(
                    evaluated_at=now,
                    sensor_name=spec.sensor_name,
                    job_name=spec.job_name,
                    asset_family=spec.asset_family,
                    reason_code="partition_not_registered",
                    message="ETF 日频等待最早缺失的共享交易日分区注册。",
                    blocked_component=_PARTITION_SET_NAME,
                    target_date=gap.first_missing_registered_date,
                    window_dates=dates,
                )
            raw_batch = spec.readiness(
                instance=context.instance,
                connection=connection,
                lake_root=context.resources.lake_root.root(),
                trade_dates=dates,
            )
        decision, status = _first_raw_decision(raw_batch)
        if decision == "all_ready":
            return _skip(
                evaluated_at=now,
                sensor_name=spec.sensor_name,
                job_name=spec.job_name,
                asset_family=spec.asset_family,
                reason_code="all_ready",
                message="最近 10 个 ETF 日频 Raw 交易日均已 ready。",
                window_dates=dates,
                raw_batch=raw_batch,
            )
        assert status is not None
        if decision == "existing_invalid":
            return _skip(
                evaluated_at=now,
                sensor_name=spec.sensor_name,
                job_name=spec.job_name,
                asset_family=spec.asset_family,
                reason_code="existing_file_check_failed",
                message="ETF 日频 Raw 已有文件或证据但检查失败，拒绝自动覆盖。",
                blocked_component=status.asset_key,
                target_date=status.trade_date,
                window_dates=dates,
                raw_status=status,
                raw_batch=raw_batch,
            )
        publication = spec.publication_probe(
            context.resources.tushare,
            status.trade_date,
        )
        if not publication.ready:
            return _skip(
                evaluated_at=now,
                sensor_name=spec.sensor_name,
                job_name=spec.job_name,
                asset_family=spec.asset_family,
                reason_code=publication.reason_code,
                message="Tushare 当日数据尚未开始发布，本次不启动 Raw。",
                blocked_component=publication.api_name,
                target_date=status.trade_date,
                window_dates=dates,
                raw_status=status,
                publication=publication,
                raw_batch=raw_batch,
            )
        run_request = build_run_request(
            run_key=build_asset_update_run_key(
                subject=spec.job_name,
                unit_id=(
                    f"{status.trade_date}:"
                    f"{ETF_DAILY_AUTOMATION_CONTRACT_REVISION}"
                ),
            ),
            partition_key=status.trade_date,
        )
        return dg.SensorResult(
            run_requests=[run_request],
            cursor=_cursor(
                evaluated_at=now,
                sensor_name=spec.sensor_name,
                job_name=spec.job_name,
                asset_family=spec.asset_family,
                decision=SensorCursorDecision.REQUEST_RUNS,
                reason_code="request_run",
                summary="ETF daily Raw sensor selected the earliest missing date",
                next_action="run the selected Raw partition",
                target_date=status.trade_date,
                window_dates=dates,
                raw_status=status,
                publication=publication,
                raw_batch=raw_batch,
            ),
        )
    except Exception as error:  # noqa: BLE001 - sensors always fail closed.
        return _skip(
            evaluated_at=now,
            sensor_name=spec.sensor_name,
            job_name=spec.job_name,
            asset_family=spec.asset_family,
            reason_code=f"sensor_error_{type(error).__name__}",
            message="ETF 日频 Raw sensor 执行失败，已 fail-closed。",
            blocked_component="sensor_evaluation",
        )


def _evaluate_silver(
    context: dg.SensorEvaluationContext,
    *,
    spec: _SilverSensorSpec,
    evaluated_at: datetime | None,
) -> dg.SensorResult:
    now = _normalize_evaluated_at(
        evaluated_at or datetime.now(CN_A_SENSOR_TIMEZONE)
    )
    if now.time() < _RUN_START:
        return _skip(
            evaluated_at=now,
            sensor_name=spec.sensor_name,
            job_name=spec.job_name,
            asset_family=spec.asset_family,
            reason_code="outside_operating_window",
            message="ETF 日频自动更新等待上海时间 21:00 运行窗口。",
        )
    try:
        context.resources.lake_root.ensure_available_for_run()
        with context.resources.duckdb.connect() as connection:
            window, gap = _window_and_registration(
                context,
                connection=connection,
                evaluated_at=now,
            )
            dates = window.expected_trade_dates
            if not dates:
                return _skip(
                    evaluated_at=now,
                    sensor_name=spec.sensor_name,
                    job_name=spec.job_name,
                    asset_family=spec.asset_family,
                    reason_code="expected_window_empty",
                    message="ETF 共享交易日历当前没有可评估日期。",
                    blocked_component="trade_calendar",
                )
            if not gap.ready:
                return _skip(
                    evaluated_at=now,
                    sensor_name=spec.sensor_name,
                    job_name=spec.job_name,
                    asset_family=spec.asset_family,
                    reason_code="partition_not_registered",
                    message="ETF 日频等待最早缺失的共享交易日分区注册。",
                    blocked_component=_PARTITION_SET_NAME,
                    target_date=gap.first_missing_registered_date,
                    window_dates=dates,
                )
            raw_batch = spec.raw_readiness(
                instance=context.instance,
                connection=connection,
                lake_root=context.resources.lake_root.root(),
                trade_dates=dates,
            )
            silver_batch = spec.silver_readiness(
                instance=context.instance,
                connection=connection,
                lake_root=context.resources.lake_root.root(),
                trade_dates=dates,
            )
        target_status: EtfDailyPartitionReadiness | None = None
        target_raw_status: EtfDailyPartitionReadiness | None = None
        for trade_date in dates:
            raw_status = raw_batch.status_for_trade_date(trade_date)
            silver_status = silver_batch.status_for_trade_date(trade_date)
            if not raw_status.ready:
                return _skip(
                    evaluated_at=now,
                    sensor_name=spec.sensor_name,
                    job_name=spec.job_name,
                    asset_family=spec.asset_family,
                    reason_code="raw_not_ready",
                    message="最早日期的 ETF 日频 Raw 尚未 ready，Silver 不越过。",
                    blocked_component=raw_status.asset_key,
                    target_date=trade_date,
                    window_dates=dates,
                    raw_status=raw_status,
                    silver_status=silver_status,
                    raw_batch=raw_batch,
                    silver_batch=silver_batch,
                )
            if silver_status.ready:
                continue
            if silver_status.materialized or silver_status.file_exists:
                return _skip(
                    evaluated_at=now,
                    sensor_name=spec.sensor_name,
                    job_name=spec.job_name,
                    asset_family=spec.asset_family,
                    reason_code="existing_file_check_failed",
                    message="ETF 日频 Silver 已有文件或证据但检查失败，拒绝自动覆盖。",
                    blocked_component=silver_status.asset_key,
                    target_date=trade_date,
                    window_dates=dates,
                    raw_status=raw_status,
                    silver_status=silver_status,
                    raw_batch=raw_batch,
                    silver_batch=silver_batch,
                )
            target_status = silver_status
            target_raw_status = raw_status
            break
        if target_status is None:
            return _skip(
                evaluated_at=now,
                sensor_name=spec.sensor_name,
                job_name=spec.job_name,
                asset_family=spec.asset_family,
                reason_code="all_ready",
                message="最近 10 个 ETF 日频 Silver 交易日均已 ready。",
                window_dates=dates,
                raw_batch=raw_batch,
                silver_batch=silver_batch,
            )
        try:
            basic_reference = select_latest_etf_basic_snapshot_reference(
                instance=context.instance,
                lake_root_path=context.resources.lake_root.root(),
                duckdb_resource=context.resources.duckdb,
                eligibility_as_of=now.date(),
                required_freshness_date=now.date(),
            )
        except Exception:  # noqa: BLE001 - latest Basic is a fail-closed gate.
            return _skip(
                evaluated_at=now,
                sensor_name=spec.sensor_name,
                job_name=spec.job_name,
                asset_family=spec.asset_family,
                reason_code="latest_basic_not_ready",
                message="最新 ETF Basic 未 ready 或不新鲜，Silver 不回退旧版本。",
                blocked_component="silver_etf_basic",
                target_date=target_status.trade_date,
                window_dates=dates,
                raw_status=target_raw_status,
                silver_status=target_status,
                raw_batch=raw_batch,
                silver_batch=silver_batch,
            )
        run_request = build_run_request(
            run_key=build_asset_update_run_key(
                subject=spec.job_name,
                unit_id=(
                    f"{target_status.trade_date}:"
                    f"{ETF_DAILY_AUTOMATION_CONTRACT_REVISION}"
                ),
            ),
            partition_key=target_status.trade_date,
        )
        return dg.SensorResult(
            run_requests=[run_request],
            cursor=_cursor(
                evaluated_at=now,
                sensor_name=spec.sensor_name,
                job_name=spec.job_name,
                asset_family=spec.asset_family,
                decision=SensorCursorDecision.REQUEST_RUNS,
                reason_code="request_run",
                summary="ETF daily Silver sensor selected the earliest missing date",
                next_action="run the selected Silver partition",
                target_date=target_status.trade_date,
                window_dates=dates,
                raw_status=target_raw_status,
                silver_status=target_status,
                basic_fingerprint=basic_reference.reference_fingerprint,
                raw_batch=raw_batch,
                silver_batch=silver_batch,
            ),
        )
    except Exception as error:  # noqa: BLE001 - sensors always fail closed.
        return _skip(
            evaluated_at=now,
            sensor_name=spec.sensor_name,
            job_name=spec.job_name,
            asset_family=spec.asset_family,
            reason_code=f"sensor_error_{type(error).__name__}",
            message="ETF 日频 Silver sensor 执行失败，已 fail-closed。",
            blocked_component="sensor_evaluation",
        )


def evaluate_raw_fund_daily_sensor(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime | None = None,
) -> dg.SensorResult:
    return _evaluate_raw(
        context,
        spec=_RAW_FUND_DAILY_SPEC,
        evaluated_at=evaluated_at,
    )


def evaluate_raw_fund_adj_sensor(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime | None = None,
) -> dg.SensorResult:
    return _evaluate_raw(
        context,
        spec=_RAW_FUND_ADJ_SPEC,
        evaluated_at=evaluated_at,
    )


def evaluate_silver_etf_daily_sensor(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime | None = None,
) -> dg.SensorResult:
    return _evaluate_silver(
        context,
        spec=_SILVER_ETF_DAILY_SPEC,
        evaluated_at=evaluated_at,
    )


def evaluate_silver_etf_adj_factor_sensor(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime | None = None,
) -> dg.SensorResult:
    return _evaluate_silver(
        context,
        spec=_SILVER_ETF_ADJ_FACTOR_SPEC,
        evaluated_at=evaluated_at,
    )


@dg.sensor(
    job=raw_fund_daily_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb", "tushare"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="上海时间 21:00 后按最早缺口触发基金日线 Raw。",
)
def raw_fund_daily_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return evaluate_raw_fund_daily_sensor(context)


@dg.sensor(
    job=raw_fund_adj_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb", "tushare"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="上海时间 21:00 后按最早缺口触发基金复权因子 Raw。",
)
def raw_fund_adj_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return evaluate_raw_fund_adj_sensor(context)


@dg.sensor(
    job=silver_etf_daily_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="上海时间 21:00 后按最早缺口触发 ETF 日线 Silver。",
)
def silver_etf_daily_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return evaluate_silver_etf_daily_sensor(context)


@dg.sensor(
    job=silver_etf_adj_factor_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="上海时间 21:00 后按最早缺口触发 ETF 复权因子 Silver。",
)
def silver_etf_adj_factor_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return evaluate_silver_etf_adj_factor_sensor(context)


__all__ = [
    "evaluate_raw_fund_adj_sensor",
    "evaluate_raw_fund_daily_sensor",
    "evaluate_silver_etf_adj_factor_sensor",
    "evaluate_silver_etf_daily_sensor",
    "raw_fund_adj_update_job_sensor",
    "raw_fund_daily_update_job_sensor",
    "silver_etf_adj_factor_update_job_sensor",
    "silver_etf_daily_update_job_sensor",
]
