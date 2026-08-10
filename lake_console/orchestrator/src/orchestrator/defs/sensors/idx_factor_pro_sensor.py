"""Current-day Raw/Silver automation for daily index technical factors."""

from dataclasses import dataclass
from datetime import datetime

import dagster as dg

from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityDateReadiness,
)
from orchestrator.defs.asset_guards.idx_factor_pro_lake_readiness import (
    raw_idx_factor_pro_lake_readiness,
    silver_idx_factor_pro_lake_readiness,
)
from orchestrator.defs.asset_guards.idx_factor_pro_source_probe import (
    IdxFactorProSourceProbeResult,
    probe_idx_factor_pro_source,
)
from orchestrator.defs.jobs.idx_factor_pro import (
    raw_tushare_idx_factor_pro_update_job,
    silver_index_factor_pro_update_job,
)
from orchestrator.defs.partitions import cn_major_index_factor_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursor_payloads import (
    build_cursor_details,
    compact_date_readiness,
)
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.idx_factor_pro import (
    IDX_FACTOR_PRO_AUTOMATION_CONTRACT_REVISION,
    IDX_FACTOR_PRO_RAW_JOB_NAME,
    IDX_FACTOR_PRO_RAW_SENSOR_NAME,
    IDX_FACTOR_PRO_SILVER_JOB_NAME,
    IDX_FACTOR_PRO_SILVER_SENSOR_NAME,
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
    SAME_DAY_PARTITION_REGISTER_START,
    is_sse_open_day,
)
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE


@dataclass(frozen=True, slots=True)
class IdxFactorProCurrentDateGate:
    trade_date: str
    window_started: bool
    open_day: bool
    registered: bool


def _load_current_date_gate(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime,
) -> IdxFactorProCurrentDateGate:
    trade_date = evaluated_at.date().isoformat()
    window_started = (
        evaluated_at.timetz().replace(tzinfo=None)
        >= SAME_DAY_PARTITION_REGISTER_START
    )
    if not window_started:
        return IdxFactorProCurrentDateGate(
            trade_date=trade_date,
            window_started=False,
            open_day=False,
            registered=False,
        )

    lake_root = context.resources.lake_root
    lake_root.ensure_available_for_run()
    calendar_path = silver_trade_calendar_path(lake_root.root())
    if not calendar_path.exists():
        raise FileNotFoundError(
            f"silver_trade_calendar file is missing: {calendar_path}"
        )
    duckdb_resource = context.resources.duckdb
    with duckdb_resource.connect() as connection:
        open_day = is_sse_open_day(connection, calendar_path, trade_date)
    registered = trade_date in set(
        context.instance.get_dynamic_partitions(
            cn_major_index_factor_trade_days.name
        )
    )
    return IdxFactorProCurrentDateGate(
        trade_date=trade_date,
        window_started=True,
        open_day=open_day,
        registered=registered,
    )


def _source_summary(
    source: IdxFactorProSourceProbeResult | None,
) -> dict[str, object] | None:
    if source is None:
        return None
    return {
        "ready": source.ready,
        "reason_code": source.reason_code,
        "expected_code_count": source.expected_code_count,
        "returned_code_count": source.returned_code_count,
        "source_row_count": source.source_row_count,
        "request_count": source.request_count,
        "retry_count": source.retry_count,
        "elapsed_ms": source.elapsed_ms,
    }


def _cursor(
    *,
    sensor_name: str,
    job_name: str,
    evaluated_at: datetime,
    trade_date: str,
    reason_code: str,
    blocked_component: str,
    selected: bool,
    summary: str,
    next_action: str,
    target: ContinuityDateReadiness | None = None,
    upstream: ContinuityDateReadiness | None = None,
    source: IdxFactorProSourceProbeResult | None = None,
) -> str:
    return build_sensor_cursor(
        evaluated_at=evaluated_at,
        decision=(
            SensorCursorDecision.REQUEST_RUNS
            if selected
            else SensorCursorDecision.SKIP
        ),
        target_date=trade_date,
        selected_count=1 if selected else 0,
        blocked_count=0 if selected or reason_code == "target_ready" else 1,
        sample_keys=(trade_date,) if selected else (),
        details=build_cursor_details(
            sensor_name=sensor_name,
            job_name=job_name,
            asset_family="idx_factor_pro",
            partition_set=cn_major_index_factor_trade_days.name,
            reason_code=reason_code,
            blocked_component=blocked_component,
            summary=summary,
            next_action=next_action,
            frontier={"current_trade_date": trade_date},
            gate_statuses={
                "target": compact_date_readiness(target),
                "upstream_raw": compact_date_readiness(upstream),
            },
            evidence={
                "contract_revision": IDX_FACTOR_PRO_AUTOMATION_CONTRACT_REVISION,
                "max_run_requests_per_tick": 1,
                "source_probe": _source_summary(source),
            },
        ),
    )


def _gate_skip(
    *,
    gate: IdxFactorProCurrentDateGate,
    sensor_name: str,
    job_name: str,
    evaluated_at: datetime,
) -> dg.SensorResult | None:
    if not gate.window_started:
        reason_code = "before_closing_window"
        skip_reason = "尚未到 16:00，暂不触发当天指数技术因子任务。"
    elif not gate.open_day:
        reason_code = "current_date_not_open"
        skip_reason = "当天不是上交所开市日，不触发指数技术因子任务。"
    elif not gate.registered:
        reason_code = "partition_not_registered"
        skip_reason = "当天指数技术因子专属分区尚未注册。"
    else:
        return None
    return dg.SensorResult(
        skip_reason=skip_reason,
        cursor=_cursor(
            sensor_name=sensor_name,
            job_name=job_name,
            evaluated_at=evaluated_at,
            trade_date=gate.trade_date,
            reason_code=reason_code,
            blocked_component=reason_code,
            selected=False,
            summary=f"idx_factor_pro automation skipped: {reason_code}",
            next_action="wait for the next automation sensor tick",
        ),
    )


def _run_request(*, job_name: str, trade_date: str) -> dg.RunRequest:
    return build_run_request(
        run_key=build_asset_update_run_key(
            subject=job_name,
            unit_id=(
                f"{trade_date}:{IDX_FACTOR_PRO_AUTOMATION_CONTRACT_REVISION}"
            ),
        ),
        partition_key=trade_date,
    )


def _evaluate_raw_sensor(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime | None = None,
) -> dg.SensorResult:
    evaluated_at = evaluated_at or datetime.now(CN_A_SENSOR_TIMEZONE)
    trade_date = evaluated_at.date().isoformat()
    try:
        gate = _load_current_date_gate(context, evaluated_at=evaluated_at)
        gate_result = _gate_skip(
            gate=gate,
            sensor_name=IDX_FACTOR_PRO_RAW_SENSOR_NAME,
            job_name=IDX_FACTOR_PRO_RAW_JOB_NAME,
            evaluated_at=evaluated_at,
        )
        if gate_result is not None:
            return gate_result

        target = raw_idx_factor_pro_lake_readiness(
            lake_root=context.resources.lake_root.root(),
            duckdb_resource=context.resources.duckdb,
            trade_date=gate.trade_date,
        )
        if target.ready:
            return dg.SensorResult(
                skip_reason="当天指数技术因子 Raw 已 ready。",
                cursor=_cursor(
                    sensor_name=IDX_FACTOR_PRO_RAW_SENSOR_NAME,
                    job_name=IDX_FACTOR_PRO_RAW_JOB_NAME,
                    evaluated_at=evaluated_at,
                    trade_date=gate.trade_date,
                    reason_code="target_ready",
                    blocked_component="none",
                    selected=False,
                    summary="current idx_factor_pro Raw partition is ready",
                    next_action="wait for the next trade date",
                    target=target,
                ),
            )
        if target.materialized:
            return dg.SensorResult(
                skip_reason="当天指数技术因子 Raw 文件已存在但检查失败，拒绝自动覆盖。",
                cursor=_cursor(
                    sensor_name=IDX_FACTOR_PRO_RAW_SENSOR_NAME,
                    job_name=IDX_FACTOR_PRO_RAW_JOB_NAME,
                    evaluated_at=evaluated_at,
                    trade_date=gate.trade_date,
                    reason_code="materialized_check_failed",
                    blocked_component="raw_lake",
                    selected=False,
                    summary="materialized idx_factor_pro Raw checks failed",
                    next_action="repair the existing Raw partition before retrying",
                    target=target,
                ),
            )

        source = probe_idx_factor_pro_source(
            tushare=context.resources.tushare,
            trade_date=gate.trade_date,
        )
        if not source.ready:
            return dg.SensorResult(
                skip_reason="Tushare 指数技术因子当天数据尚未完整返回。",
                cursor=_cursor(
                    sensor_name=IDX_FACTOR_PRO_RAW_SENSOR_NAME,
                    job_name=IDX_FACTOR_PRO_RAW_JOB_NAME,
                    evaluated_at=evaluated_at,
                    trade_date=gate.trade_date,
                    reason_code=source.reason_code,
                    blocked_component="tushare_idx_factor_pro_source",
                    selected=False,
                    summary="single-page idx_factor_pro source probe is incomplete",
                    next_action="wait for the complete same-day source page",
                    target=target,
                    source=source,
                ),
            )
        return dg.SensorResult(
            run_requests=[
                _run_request(
                    job_name=IDX_FACTOR_PRO_RAW_JOB_NAME,
                    trade_date=gate.trade_date,
                )
            ],
            cursor=_cursor(
                sensor_name=IDX_FACTOR_PRO_RAW_SENSOR_NAME,
                job_name=IDX_FACTOR_PRO_RAW_JOB_NAME,
                evaluated_at=evaluated_at,
                trade_date=gate.trade_date,
                reason_code="request_run",
                blocked_component="none",
                selected=True,
                summary="source probe is ready; request current Raw partition",
                next_action="run the single-partition Raw job",
                target=target,
                source=source,
            ),
        )
    except Exception as error:  # noqa: BLE001 - sensor fails closed.
        return dg.SensorResult(
            skip_reason="指数技术因子 Raw sensor 执行失败，已 fail-closed。",
            cursor=_cursor(
                sensor_name=IDX_FACTOR_PRO_RAW_SENSOR_NAME,
                job_name=IDX_FACTOR_PRO_RAW_JOB_NAME,
                evaluated_at=evaluated_at,
                trade_date=trade_date,
                reason_code="sensor_error",
                blocked_component="sensor",
                selected=False,
                summary="idx_factor_pro Raw sensor failed closed",
                next_action=f"inspect {type(error).__name__} and retry",
            ),
        )


def _evaluate_silver_sensor(
    context: dg.SensorEvaluationContext,
    *,
    evaluated_at: datetime | None = None,
) -> dg.SensorResult:
    evaluated_at = evaluated_at or datetime.now(CN_A_SENSOR_TIMEZONE)
    trade_date = evaluated_at.date().isoformat()
    try:
        gate = _load_current_date_gate(context, evaluated_at=evaluated_at)
        gate_result = _gate_skip(
            gate=gate,
            sensor_name=IDX_FACTOR_PRO_SILVER_SENSOR_NAME,
            job_name=IDX_FACTOR_PRO_SILVER_JOB_NAME,
            evaluated_at=evaluated_at,
        )
        if gate_result is not None:
            return gate_result

        target = silver_idx_factor_pro_lake_readiness(
            lake_root=context.resources.lake_root.root(),
            duckdb_resource=context.resources.duckdb,
            trade_date=gate.trade_date,
        )
        if target.ready:
            return dg.SensorResult(
                skip_reason="当天指数技术因子 Silver 已 ready。",
                cursor=_cursor(
                    sensor_name=IDX_FACTOR_PRO_SILVER_SENSOR_NAME,
                    job_name=IDX_FACTOR_PRO_SILVER_JOB_NAME,
                    evaluated_at=evaluated_at,
                    trade_date=gate.trade_date,
                    reason_code="target_ready",
                    blocked_component="none",
                    selected=False,
                    summary="current idx_factor_pro Silver partition is ready",
                    next_action="wait for the next trade date",
                    target=target,
                ),
            )
        if target.materialized:
            return dg.SensorResult(
                skip_reason="当天指数技术因子 Silver 文件已存在但检查失败，拒绝自动覆盖。",
                cursor=_cursor(
                    sensor_name=IDX_FACTOR_PRO_SILVER_SENSOR_NAME,
                    job_name=IDX_FACTOR_PRO_SILVER_JOB_NAME,
                    evaluated_at=evaluated_at,
                    trade_date=gate.trade_date,
                    reason_code="materialized_check_failed",
                    blocked_component="silver_lake",
                    selected=False,
                    summary="materialized idx_factor_pro Silver checks failed",
                    next_action="repair the existing Silver partition before retrying",
                    target=target,
                ),
            )

        upstream = raw_idx_factor_pro_lake_readiness(
            lake_root=context.resources.lake_root.root(),
            duckdb_resource=context.resources.duckdb,
            trade_date=gate.trade_date,
        )
        if not upstream.ready:
            return dg.SensorResult(
                skip_reason="当天指数技术因子 Raw 尚未通过全部 blocking checks。",
                cursor=_cursor(
                    sensor_name=IDX_FACTOR_PRO_SILVER_SENSOR_NAME,
                    job_name=IDX_FACTOR_PRO_SILVER_JOB_NAME,
                    evaluated_at=evaluated_at,
                    trade_date=gate.trade_date,
                    reason_code=(
                        "raw_materialized_check_failed"
                        if upstream.materialized
                        else "raw_not_ready"
                    ),
                    blocked_component="raw_lake",
                    selected=False,
                    summary="same-date Raw partition is not ready",
                    next_action="wait for or repair the same-date Raw partition",
                    target=target,
                    upstream=upstream,
                ),
            )
        return dg.SensorResult(
            run_requests=[
                _run_request(
                    job_name=IDX_FACTOR_PRO_SILVER_JOB_NAME,
                    trade_date=gate.trade_date,
                )
            ],
            cursor=_cursor(
                sensor_name=IDX_FACTOR_PRO_SILVER_SENSOR_NAME,
                job_name=IDX_FACTOR_PRO_SILVER_JOB_NAME,
                evaluated_at=evaluated_at,
                trade_date=gate.trade_date,
                reason_code="request_run",
                blocked_component="none",
                selected=True,
                summary="same-date Raw is ready; request current Silver partition",
                next_action="run the single-partition Silver job",
                target=target,
                upstream=upstream,
            ),
        )
    except Exception as error:  # noqa: BLE001 - sensor fails closed.
        return dg.SensorResult(
            skip_reason="指数技术因子 Silver sensor 执行失败，已 fail-closed。",
            cursor=_cursor(
                sensor_name=IDX_FACTOR_PRO_SILVER_SENSOR_NAME,
                job_name=IDX_FACTOR_PRO_SILVER_JOB_NAME,
                evaluated_at=evaluated_at,
                trade_date=trade_date,
                reason_code="sensor_error",
                blocked_component="sensor",
                selected=False,
                summary="idx_factor_pro Silver sensor failed closed",
                next_action=f"inspect {type(error).__name__} and retry",
            ),
        )


@dg.sensor(
    name=IDX_FACTOR_PRO_RAW_SENSOR_NAME,
    job=raw_tushare_idx_factor_pro_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb", "tushare"},
    description="16:00 后按当天分区探测 idx_factor_pro 并最多触发一个 Raw run。",
)
def raw_tushare_idx_factor_pro_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return _evaluate_raw_sensor(context)


@dg.sensor(
    name=IDX_FACTOR_PRO_SILVER_SENSOR_NAME,
    job=silver_index_factor_pro_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    required_resource_keys={"lake_root", "duckdb"},
    description="同日 Raw 通过全部 blocking checks 后最多触发一个 Silver run。",
)
def silver_index_factor_pro_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return _evaluate_silver_sensor(context)


__all__ = [
    "IdxFactorProCurrentDateGate",
    "_evaluate_raw_sensor",
    "_evaluate_silver_sensor",
    "_load_current_date_gate",
    "raw_tushare_idx_factor_pro_update_job_sensor",
    "silver_index_factor_pro_update_job_sensor",
]
