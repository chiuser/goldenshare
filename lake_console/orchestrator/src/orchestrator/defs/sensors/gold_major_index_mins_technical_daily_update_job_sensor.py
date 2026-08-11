"""Run-status automation for daily major-index minute technical assets."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import dagster as dg

from orchestrator.defs.asset_guards.major_index_mins_lake_readiness import (
    batch_silver_major_index_mins_lake_readiness,
)
from orchestrator.defs.asset_guards.major_index_mins_technical import (
    MajorIndexMinsTechnicalReadiness,
    major_index_mins_technical_state_readiness,
    major_index_mins_technical_target_readiness,
)
from orchestrator.defs.asset_guards.stk_mins_continuity import (
    is_first_expected_trade_date,
    load_stock_mins_expected_trade_dates,
    previous_expected_trade_date,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.health.lake_root import assert_lake_root_available_for_run
from orchestrator.defs.jobs.gold_major_index_mins_technical_daily_update import (
    gold_major_index_mins_technical_daily_update_job,
)
from orchestrator.defs.jobs.major_index_mins import (
    silver_major_index_mins_update_job,
)
from orchestrator.defs.partitions import cn_major_index_mins_trade_days
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, silver_trade_calendar_path
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_HISTORY_START_DATE,
    normalize_major_index_mins_trade_date,
)
from orchestrator.defs.run_contracts.major_index_mins_technical import (
    MAJOR_INDEX_MINS_TECHNICAL_AUTOMATION_CONTRACT_REVISION,
    MAJOR_INDEX_MINS_TECHNICAL_JOB_NAME,
    MAJOR_INDEX_MINS_TECHNICAL_SENSOR_NAME,
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

DAGSTER_PARTITION_TAG = "dagster/partition"
DAGSTER_PARTITION_RANGE_START_TAG = "dagster/asset_partition_range_start"
DAGSTER_PARTITION_RANGE_END_TAG = "dagster/asset_partition_range_end"


@dataclass(frozen=True, slots=True)
class MajorIndexMinsTechnicalDailyDecision:
    target_trade_date: str | None
    previous_trade_date: str | None
    selected_trade_date: str | None
    reason_code: str
    reason: str
    next_action: str


def extract_unique_major_index_mins_partition_key(
    *,
    partition_key: object | None,
    tag_values: Mapping[str, object] | None,
) -> str | None:
    """Return one ISO partition key; reject multi-partition ranges and conflicts."""

    normalized_tags = tag_values or {}
    range_start = normalized_tags.get(DAGSTER_PARTITION_RANGE_START_TAG)
    range_end = normalized_tags.get(DAGSTER_PARTITION_RANGE_END_TAG)
    if (range_start is None) != (range_end is None):
        return None

    candidates = [
        value
        for value in (
            partition_key,
            normalized_tags.get(DAGSTER_PARTITION_TAG),
        )
        if value is not None and str(value).strip()
    ]
    if range_start is not None and range_end is not None:
        try:
            normalized_range_start = normalize_major_index_mins_trade_date(
                str(range_start)
            )
            normalized_range_end = normalize_major_index_mins_trade_date(
                str(range_end)
            )
        except ValueError:
            return None
        if normalized_range_start != normalized_range_end:
            return None
        candidates.append(normalized_range_start)

    normalized: set[str] = set()
    try:
        normalized.update(
            normalize_major_index_mins_trade_date(str(value))
            for value in candidates
        )
    except ValueError:
        return None
    if len(normalized) != 1:
        return None
    return normalized.pop()


def build_major_index_mins_technical_daily_decision(
    *,
    target_trade_date: str | None,
    previous_trade_date: str | None,
    is_historical_baseline: bool,
    source_ready: bool,
    target_readiness: MajorIndexMinsTechnicalReadiness | None,
    previous_state_readiness: MajorIndexMinsTechnicalReadiness | None,
) -> MajorIndexMinsTechnicalDailyDecision:
    if target_trade_date is None:
        return MajorIndexMinsTechnicalDailyDecision(
            target_trade_date=None,
            previous_trade_date=None,
            selected_trade_date=None,
            reason_code="partition_not_unique",
            reason="触发 run 未提供唯一的主要指数分钟线交易日分区。",
            next_action="确认 Silver run 只处理一个 dagster/partition 后重试。",
        )
    if not source_ready:
        return MajorIndexMinsTechnicalDailyDecision(
            target_trade_date=target_trade_date,
            previous_trade_date=previous_trade_date,
            selected_trade_date=None,
            reason_code="source_not_ready",
            reason="目标交易日七频度主要指数分钟线 Silver 尚未全部 ready。",
            next_action="先修复同日 Silver 文件或 blocking checks，再重新触发。",
        )
    if target_readiness is None:
        raise ValueError("target_readiness is required when source is ready")
    if target_readiness.ready:
        return MajorIndexMinsTechnicalDailyDecision(
            target_trade_date=target_trade_date,
            previous_trade_date=previous_trade_date,
            selected_trade_date=None,
            reason_code="target_ready",
            reason="目标交易日 14 个技术指标与状态资产已经 ready。",
            next_action="无需重复执行，等待下一个 Silver 成功分区。",
        )
    if not target_readiness.all_missing:
        return MajorIndexMinsTechnicalDailyDecision(
            target_trade_date=target_trade_date,
            previous_trade_date=previous_trade_date,
            selected_trade_date=None,
            reason_code=target_readiness.reason_code,
            reason="目标交易日资产已部分生成或语义校验失败，自动化已 fail-closed。",
            next_action="人工检查目标文件和 blocking checks；禁止自动覆盖。",
        )
    if not is_historical_baseline:
        if previous_trade_date is None:
            return MajorIndexMinsTechnicalDailyDecision(
                target_trade_date=target_trade_date,
                previous_trade_date=None,
                selected_trade_date=None,
                reason_code="previous_trade_date_missing",
                reason="无法解析目标交易日的上一 expected 交易日。",
                next_action="先修复主要指数分钟线 expected calendar 连续性。",
            )
        if previous_state_readiness is None or not previous_state_readiness.ready:
            return MajorIndexMinsTechnicalDailyDecision(
                target_trade_date=target_trade_date,
                previous_trade_date=previous_trade_date,
                selected_trade_date=None,
                reason_code=(
                    previous_state_readiness.reason_code
                    if previous_state_readiness is not None
                    else "previous_state_not_ready"
                ),
                reason="上一 expected 交易日七频度递推状态尚未全部 ready。",
                next_action="先修复上一交易日 state，再重新触发当日增量。",
            )
    return MajorIndexMinsTechnicalDailyDecision(
        target_trade_date=target_trade_date,
        previous_trade_date=previous_trade_date,
        selected_trade_date=target_trade_date,
        reason_code="request_run",
        reason="同日 Silver 与前态门禁全部 ready，提交技术指标日常增量。",
        next_action="等待目标 job 完成并检查 70 个 blocking checks。",
    )


def _load_expected_trade_dates(
    *,
    connection,
    lake_root: Path,
) -> tuple[str, ...]:
    calendar_path = silver_trade_calendar_path(lake_root)
    if not calendar_path.exists():
        raise FileNotFoundError(
            f"silver_trade_calendar file is missing: {calendar_path}"
        )
    return load_stock_mins_expected_trade_dates(
        connection,
        calendar_path,
        min_trade_date=MAJOR_INDEX_MINS_HISTORY_START_DATE,
        evaluated_at=datetime.now(CN_A_SENSOR_TIMEZONE),
        same_day_register_start=None,
    )


def _run_request_for_trade_date(trade_date: str) -> dg.RunRequest:
    return build_run_request(
        run_key=build_asset_update_run_key(
            subject=MAJOR_INDEX_MINS_TECHNICAL_JOB_NAME,
            unit_id=(
                f"{trade_date}:"
                f"{MAJOR_INDEX_MINS_TECHNICAL_AUTOMATION_CONTRACT_REVISION}"
            ),
        ),
        partition_key=trade_date,
    )


def _evaluate_daily_run_status_decision(
    *,
    context: dg.RunStatusSensorContext,
    target_trade_date: str,
) -> MajorIndexMinsTechnicalDailyDecision:
    lake_root = Path(DEFAULT_LAKE_ROOT)
    assert_lake_root_available_for_run(lake_root)
    registered_trade_days = tuple(
        sorted(
            context.instance.get_dynamic_partitions(
                cn_major_index_mins_trade_days.name
            )
        )
    )
    with connect_configured_duckdb() as connection:
        expected_trade_dates = _load_expected_trade_dates(
            connection=connection,
            lake_root=lake_root,
        )
        if target_trade_date not in expected_trade_dates:
            return MajorIndexMinsTechnicalDailyDecision(
                target_trade_date=target_trade_date,
                previous_trade_date=None,
                selected_trade_date=None,
                reason_code="partition_not_expected",
                reason="目标分区不在主要指数分钟线 expected calendar 中。",
                next_action="核对专属动态分区和 Silver 触发 run 的交易日。",
            )
        previous_trade_date = previous_expected_trade_date(
            expected_trade_dates,
            target_trade_date,
        )
        source_status = batch_silver_major_index_mins_lake_readiness(
            connection=connection,
            lake_root=lake_root,
            expected_trade_dates=(target_trade_date,),
            registered_trade_days=registered_trade_days,
        ).status_for_trade_date(target_trade_date)
        if not source_status.ready:
            return build_major_index_mins_technical_daily_decision(
                target_trade_date=target_trade_date,
                previous_trade_date=previous_trade_date,
                is_historical_baseline=is_first_expected_trade_date(
                    expected_trade_dates,
                    target_trade_date,
                ),
                source_ready=False,
                target_readiness=None,
                previous_state_readiness=None,
            )

        target_readiness = major_index_mins_technical_target_readiness(
            connection=connection,
            lake_root=lake_root,
            trade_date=target_trade_date,
            expected_trade_dates=expected_trade_dates,
        )
        is_historical_baseline = is_first_expected_trade_date(
            expected_trade_dates,
            target_trade_date,
        )
        previous_state_readiness = None
        if (
            target_readiness.all_missing
            and not is_historical_baseline
            and previous_trade_date is not None
        ):
            previous_state_readiness = major_index_mins_technical_state_readiness(
                connection=connection,
                lake_root=lake_root,
                trade_date=previous_trade_date,
                expected_trade_dates=expected_trade_dates,
            )
        return build_major_index_mins_technical_daily_decision(
            target_trade_date=target_trade_date,
            previous_trade_date=previous_trade_date,
            is_historical_baseline=is_historical_baseline,
            source_ready=True,
            target_readiness=target_readiness,
            previous_state_readiness=previous_state_readiness,
        )


@dg.run_status_sensor(
    name=MAJOR_INDEX_MINS_TECHNICAL_SENSOR_NAME,
    run_status=dg.DagsterRunStatus.SUCCESS,
    request_job=gold_major_index_mins_technical_daily_update_job,
    monitored_jobs=[silver_major_index_mins_update_job],
    default_status=dg.DefaultSensorStatus.STOPPED,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
    description=(
        "Silver 主要指数分钟线单日成功且全部 ready 后，"
        "触发七频度技术指标与状态的单分区更新。"
    ),
)
def gold_major_index_mins_technical_daily_update_job_sensor(
    context: dg.RunStatusSensorContext,
) -> dg.RunRequest | dg.SkipReason:
    target_trade_date = extract_unique_major_index_mins_partition_key(
        partition_key=getattr(context, "partition_key", None),
        tag_values=getattr(context.dagster_run, "tags", None),
    )
    if target_trade_date is None:
        decision = build_major_index_mins_technical_daily_decision(
            target_trade_date=None,
            previous_trade_date=None,
            is_historical_baseline=False,
            source_ready=False,
            target_readiness=None,
            previous_state_readiness=None,
        )
        return dg.SkipReason(f"{decision.reason} 下一步：{decision.next_action}")
    try:
        decision = _evaluate_daily_run_status_decision(
            context=context,
            target_trade_date=target_trade_date,
        )
    except Exception as error:  # noqa: BLE001 - automation must fail closed.
        return dg.SkipReason(
            "主要指数分钟线技术指标 sensor 执行失败，已 fail-closed。"
            f" error_type={type(error).__name__}"
        )
    if decision.selected_trade_date is None:
        return dg.SkipReason(f"{decision.reason} 下一步：{decision.next_action}")
    return _run_request_for_trade_date(decision.selected_trade_date)


__all__ = [
    "MajorIndexMinsTechnicalDailyDecision",
    "build_major_index_mins_technical_daily_decision",
    "extract_unique_major_index_mins_partition_key",
    "gold_major_index_mins_technical_daily_update_job_sensor",
]
