"""Submit the earliest unfinished Gold partition after its upstream checks pass."""

from collections import defaultdict
from datetime import datetime

import dagster as dg
from dagster._core.storage.asset_check_execution_record import (
    AssetCheckExecutionRecordStatus,
)
from dagster._core.storage.tags import PARTITION_NAME_TAG, RUN_KEY_TAG

from orchestrator.defs.assets.major_index_quantitative_structure import (
    STRUCTURE_UPSTREAM_SPECS,
)
from orchestrator.defs.io.major_index_quantitative_structure import (
    structure_trade_dates,
)
from orchestrator.defs.jobs.major_index_quantitative_structure_update import (
    gold_major_index_quantitative_structure_update_job,
)
from orchestrator.defs.partitions import (
    cn_major_index_factor_trade_days,
    cn_major_index_mins_trade_days,
    cn_major_index_quantitative_structure_trade_days,
)
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
    load_sensor_cursor,
)
from orchestrator.defs.run_contracts.major_index_quantitative_structure import (
    STRUCTURE_ASSET,
    STRUCTURE_CHECK_START,
    STRUCTURE_CHECKS,
    STRUCTURE_JOB,
    STRUCTURE_SENSOR_INTERVAL_SECONDS,
    STRUCTURE_SENSOR_LOOKBACK,
)
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.sensors.readiness import (
    CN_A_SENSOR_TIMEZONE,
    partition_dataset_readiness_status_from_latest_checks,
)

STRUCTURE_ASSET_KEY = dg.AssetKey(STRUCTURE_ASSET)
STRUCTURE_CHECK_KEYS = [dg.AssetCheckKey(STRUCTURE_ASSET_KEY, name) for name in STRUCTURE_CHECKS]


def _completed_structure_dates(instance, partition_keys: list[str]) -> dict[str, int]:
    infos = instance.event_log_storage.get_asset_check_partition_info(
        STRUCTURE_CHECK_KEYS, partition_keys=partition_keys,
    )
    passed = defaultdict(dict)
    for info in infos:
        if (
            info.latest_execution_status == AssetCheckExecutionRecordStatus.SUCCEEDED
            and info.latest_materialization_storage_id is not None
            and info.latest_target_materialization_storage_id == info.latest_materialization_storage_id
        ):
            passed[info.partition_key][info.check_key.name] = info.latest_materialization_storage_id
    return {
        day: next(iter(checks.values()))
        for day, checks in passed.items()
        if set(checks) == set(STRUCTURE_CHECKS) and len(set(checks.values())) == 1
    }


def _skip_structure_date(now: datetime, day: str | None, summary: str, next_action: str) -> dg.SensorResult:
    return dg.SensorResult(
        skip_reason=f"{day + ' ' if day else ''}{summary} {next_action}",
        cursor=build_sensor_cursor(
            evaluated_at=now, decision=SensorCursorDecision.SKIP, target_date=day,
            details={"summary": summary, "next_action": next_action},
        ),
    )


@dg.sensor(
    job=gold_major_index_quantitative_structure_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=STRUCTURE_SENSOR_INTERVAL_SECONDS,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="上海时间 18:00 起检查同日行情和指标，齐备后启动待完成的量化结构分区。",
)
def gold_major_index_quantitative_structure_update_job_sensor(
    context: dg.SensorEvaluationContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.SensorResult:
    now = datetime.now(CN_A_SENSOR_TIMEZONE)
    if now.time() < STRUCTURE_CHECK_START:
        return dg.SensorResult(skip_reason="上海时间 18:00 起检查量化结构日更。")
    if not silver_trade_calendar_path(lake_root.root()).is_file():
        return dg.SensorResult(skip_reason="等待 SSE 交易日历文件。")
    with duckdb.connect() as connection:
        days = [
            day.isoformat() for day in structure_trade_dates(
                connection, lake_root.root(), now.date(),
                recent=STRUCTURE_SENSOR_LOOKBACK,
            )
        ]
    if not days:
        return _skip_structure_date(now, None, "当前没有应处理交易日。", "等待下次检查。")

    instance = context.instance
    manual_action = "上游就绪后，用同一个日更 job 手动重跑该分区。"
    previous_target = load_sensor_cursor(context.cursor).get("target_date")
    if previous_target and previous_target < days[0]:
        if previous_target in _completed_structure_dates(instance, [previous_target]):
            return _skip_structure_date(now, None, f"{previous_target} 已完成。", "下次检查近期日期。")
        return _skip_structure_date(now, previous_target, "待完成日已超出自动窗口。", manual_action)

    completed = _completed_structure_dates(instance, days)
    day = next((day for day in days if day not in completed), None)
    if day is None:
        return _skip_structure_date(now, None, "近期量化结构分区均已完成。", "等待下次检查。")
    for partitions in (
        cn_major_index_quantitative_structure_trade_days,
        cn_major_index_factor_trade_days,
        cn_major_index_mins_trade_days,
    ):
        if not instance.has_dynamic_partition(partitions.name, day):
            return _skip_structure_date(now, day, f"缺少分区 {partitions.name}。", "等待登记。")

    request = build_run_request(
        run_key=build_asset_update_run_key(subject=f"{STRUCTURE_ASSET}_update", unit_id=day),
        partition_key=day,
    )
    runs = instance.get_runs(
        filters=dg.RunsFilter(job_name=STRUCTURE_JOB, tags={PARTITION_NAME_TAG: day}), limit=1,
    )
    latest_run = runs[0] if runs else None
    if latest_run and not latest_run.is_finished:
        return _skip_structure_date(now, day, "分区已有运行中的作业。", "等待作业完成。")
    materializations = instance.fetch_materializations(
        dg.AssetRecordsFilter(asset_key=STRUCTURE_ASSET_KEY, asset_partitions=[day]), limit=1,
    ).records
    if materializations:
        return _skip_structure_date(now, day, "已有产出，两项检查尚未通过。", manual_action)
    if latest_run and (
        latest_run.status != dg.DagsterRunStatus.SUCCESS
        or latest_run.tags.get(RUN_KEY_TAG) == request.run_key
    ):
        return _skip_structure_date(now, day, "上次作业未产出结果。", manual_action)
    readiness = partition_dataset_readiness_status_from_latest_checks(
        instance, STRUCTURE_UPSTREAM_SPECS, partition_key=day,
    )
    if not readiness.ready:
        return _skip_structure_date(now, day, readiness.reason, "等待当日上游全部就绪。")
    return dg.SensorResult(
        run_requests=[request],
        cursor=build_sensor_cursor(
            evaluated_at=now, decision=SensorCursorDecision.REQUEST_RUNS,
            target_date=day, selected_count=1,
            details={"summary": "当日上游已就绪。", "next_action": "等待日更作业完成。"},
        ),
    )
