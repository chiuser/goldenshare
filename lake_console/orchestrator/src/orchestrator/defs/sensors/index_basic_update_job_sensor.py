"""Submit the index basic snapshot refresh once per eligible evening."""

from datetime import datetime, time
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo

import dagster as dg
from dagster._core.storage.asset_check_execution_record import (
    AssetCheckExecutionRecordStatus,
)
from dagster._core.storage.tags import RUN_KEY_TAG, SENSOR_NAME_TAG

from orchestrator.defs.catalog.lake_assets import (
    RAW_INDEX_BASIC_CHECKS,
    SILVER_INDEX_BASIC_CHECKS,
)
from orchestrator.defs.io.index_basic_publication import (
    INDEX_BASIC_COVERAGE_METADATA_KEY,
)
from orchestrator.defs.partitions import cn_a_index_trade_days
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.run_contracts.configs import (
    build_index_basic_update_job_run_config,
)
from orchestrator.defs.run_contracts.cursor_payloads import build_cursor_details
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
)
from orchestrator.defs.run_contracts.metadata import READY_FOR_TRADE_DATE_METADATA_KEY
from orchestrator.defs.run_contracts.requests import build_run_request
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)

_SENSOR_NAME = "index_basic_update_job_sensor"
_JOB_NAME = "index_basic_update_job"
_TIMEZONE = ZoneInfo("Asia/Shanghai")
_WINDOW_START = time(18, 0)
_RAW = dg.AssetKey("raw_tushare_index_basic")
_SILVER = dg.AssetKey("silver_index_basic")
_ASSET_KEYS = (_RAW, _SILVER)
_CHECK_KEYS = tuple(
    dg.AssetCheckKey(asset, name)
    for asset, names in (
        (_RAW, RAW_INDEX_BASIC_CHECKS),
        (_SILVER, SILVER_INDEX_BASIC_CHECKS),
    )
    for name in names
)
_COVERAGE_CHECK_KEYS = frozenset(
    (
        dg.AssetCheckKey(_RAW, "raw_index_basic_contract_check"),
        dg.AssetCheckKey(_SILVER, "silver_index_basic_lifecycle_domain_check"),
    )
)
_ACTIVE_STATUSES = (
    dg.DagsterRunStatus.NOT_STARTED,
    dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.STARTING,
    dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
)


class _QueryBudgetExceeded(ValueError):
    """A metadata query returned more records than the sensor can use."""


def _lake_available() -> bool:
    lake = Path(DEFAULT_LAKE_ROOT)
    return (
        lake.parent.is_mount()
        and lake.is_dir()
        and Path(DEFAULT_LAKE_STAGING_ROOT).is_dir()
    )


def _metadata_value(metadata, key):
    return getattr(metadata.get(key), "value", None)


def _coverage(metadata) -> dict:
    value = _metadata_value(metadata, INDEX_BASIC_COVERAGE_METADATA_KEY)
    return value if isinstance(value, dict) else {}


def _evening_batch(raw, silver, day: str) -> str | None:
    if (
        raw is None
        or silver is None
        or not raw.asset_materialization
        or not silver.asset_materialization
    ):
        return None
    raw_coverage = _coverage(raw.asset_materialization.metadata)
    silver_metadata = silver.asset_materialization.metadata
    silver_coverage = _coverage(silver_metadata)
    batch = raw_coverage.get("batch_id")
    raw_digest = raw_coverage.get("sha256")
    if (
        not isinstance(batch, str)
        or not batch
        or not isinstance(raw_digest, str)
        or not raw_digest
        or raw_coverage.get("passed") is not True
        or silver_coverage.get("passed") is not True
        or silver_coverage.get("batch_id") != batch
        or silver_coverage.get("raw_sha256") != raw_digest
        or _metadata_value(silver_metadata, READY_FOR_TRADE_DATE_METADATA_KEY) != day
    ):
        return None
    fetched_at = raw_coverage.get("fetched_at")
    if not isinstance(fetched_at, str):
        return None
    try:
        observed = datetime.fromisoformat(fetched_at)
    except ValueError:
        return None
    if observed.utcoffset() is None:
        return None
    local = observed.astimezone(_TIMEZONE)
    return (
        batch
        if local.date().isoformat() == day and local.time() >= _WINDOW_START
        else None
    )


def _matches_check(key, check, materialization, batch: str) -> bool:
    if check is None or check.status != AssetCheckExecutionRecordStatus.SUCCEEDED:
        return False
    evaluation = check.evaluation
    if evaluation is None or not evaluation.passed or not evaluation.blocking:
        return False
    target = evaluation.target_materialization_data
    if (
        evaluation.asset_key != key.asset_key
        or evaluation.check_name != key.name
        or evaluation.partition is not None
        or target is None
        or target.storage_id != materialization.storage_id
        or target.run_id != materialization.run_id
    ):
        return False
    if key in _COVERAGE_CHECK_KEYS:
        coverage = _coverage(evaluation.metadata)
        return (
            coverage.get("passed") is True
            and coverage.get("batch_id") == batch
            and coverage.get("materialization_id") == materialization.storage_id
        )
    return True


def _within_budget(records, limit: int):
    if len(records) > limit:
        raise _QueryBudgetExceeded(
            f"Read {len(records)} records with a limit of {limit}"
        )
    return records


def _delivered_this_evening(instance, day: str) -> bool:
    assets = _within_budget(instance.get_asset_records(_ASSET_KEYS), len(_ASSET_KEYS))
    records = {
        row.asset_entry.asset_key: row.asset_entry.last_materialization_record
        for row in assets
    }
    batch = _evening_batch(records.get(_RAW), records.get(_SILVER), day)
    if batch is None:
        return False

    checks = _within_budget(
        instance.event_log_storage.get_latest_asset_check_execution_by_key(_CHECK_KEYS),
        len(_CHECK_KEYS),
    )
    if not all(
        _matches_check(key, checks.get(key), records[key.asset_key], batch)
        for key in _CHECK_KEYS
    ):
        return False

    run_ids = sorted(
        {row.run_id for row in records.values()}
        | {checks[key].run_id for key in _CHECK_KEYS}
    )
    runs = _within_budget(
        instance.get_run_records(
            filters=dg.RunsFilter(run_ids=run_ids), limit=len(run_ids)
        ),
        len(run_ids),
    )
    last_materialization = max(row.timestamp for row in records.values())
    return any(
        row.dagster_run.job_name == _JOB_NAME
        and row.dagster_run.status == dg.DagsterRunStatus.SUCCESS
        and (row.dagster_run.root_run_id or row.dagster_run.run_id) == batch
        and row.end_time is not None
        and row.end_time >= last_materialization
        for row in runs
    )


def evaluate_index_basic_update(
    context: dg.SensorEvaluationContext, now: datetime
) -> dg.SensorResult:
    started = perf_counter()
    local = now.astimezone(_TIMEZONE)
    day = local.date().isoformat()

    def result(reason, summary, next_action, *, component=None, request=None):
        return dg.SensorResult(
            run_requests=[request] if request else [],
            skip_reason=None if request else dg.SkipReason(summary),
            cursor=build_sensor_cursor(
                evaluated_at=local,
                decision=SensorCursorDecision.REQUEST_RUNS
                if request
                else SensorCursorDecision.SKIP,
                target_date=day,
                selected_count=int(request is not None),
                blocked_count=int(component is not None),
                sample_keys=(day,),
                details=build_cursor_details(
                    sensor_name=_SENSOR_NAME,
                    job_name=_JOB_NAME,
                    asset_family="index_basic",
                    partition_set=cn_a_index_trade_days.name,
                    reason_code=reason,
                    blocked_component=component,
                    summary=summary,
                    next_action=next_action,
                    performance_ms={
                        "total": round((perf_counter() - started) * 1000, 3)
                    },
                ),
            ),
        )

    if not _lake_available():
        return result(
            "lake_unavailable",
            "正式 Lake 或 staging 尚不可用。",
            "恢复挂载后等待下一轮。",
            component="lake_root",
        )
    if local.time() < _WINDOW_START:
        return result("outside_window", "尚未到北京时间 18:00。", "等待当晚轮询。")

    instance = context.instance
    try:
        if not instance.has_dynamic_partition(cn_a_index_trade_days.name, day):
            return result(
                "date_not_registered",
                f"指数交易日 {day} 尚未登记。",
                "登记后等待当晚轮询。",
                component=cn_a_index_trade_days.name,
            )
        request = build_run_request(
            run_key=build_asset_update_run_key(subject=_JOB_NAME, unit_id=day),
            run_config=build_index_basic_update_job_run_config(
                scheduled_trade_date=day
            ),
        )
        submitted = _within_budget(
            instance.get_run_records(
                filters=dg.RunsFilter(
                    job_name=_JOB_NAME,
                    tags={SENSOR_NAME_TAG: _SENSOR_NAME, RUN_KEY_TAG: request.run_key},
                ),
                limit=1,
            ),
            1,
        )
        if submitted:
            status = submitted[0].dagster_run.status
            if status in (dg.DagsterRunStatus.FAILURE, dg.DagsterRunStatus.CANCELED):
                status_label = (
                    "失败" if status == dg.DagsterRunStatus.FAILURE else "取消"
                )
                return result(
                    "attempt_failed",
                    f"{day} 的自动更新已{status_label}。",
                    "查找原运行并从同一批次人工恢复。",
                    component=_JOB_NAME,
                )
            return result(
                "already_submitted", f"{day} 的自动更新已提交。", "查看原运行结果。"
            )
        active = _within_budget(
            instance.get_run_records(
                filters=dg.RunsFilter(
                    job_name=_JOB_NAME,
                    statuses=_ACTIVE_STATUSES,
                ),
                limit=1,
            ),
            1,
        )
        if active:
            return result(
                "job_active",
                "指数基础信息更新已排队或正在运行。",
                "等待现有运行结束。",
                component=_JOB_NAME,
            )
        if _delivered_this_evening(instance, day):
            return result(
                "already_delivered",
                f"{day} 晚间的 Raw 与 Silver 已同批交付。",
                "查看本批发布和 Check 证据。",
            )
    except _QueryBudgetExceeded as error:
        context.log.warning("Index basic sensor query budget exceeded: %s", error)
        return result(
            "query_budget_exceeded",
            "本轮 DG 查询返回的记录超过设计上限。",
            "检查查询范围后等待下一轮。",
            component=_JOB_NAME,
        )
    except Exception as error:  # noqa: BLE001 -- An unavailable ledger cannot authorize a submit.
        context.log.warning(
            "Index basic sensor input unavailable: %s", type(error).__name__
        )
        return result(
            "evidence_unavailable",
            "本轮无法可靠读取交付记录。",
            "检查 DG 查询后等待下一轮。",
            component=_JOB_NAME,
        )

    return result(
        "request_run",
        f"提交 {day} 指数基础信息 Raw 和 Silver 日更。",
        "等待本次 Job 及 Check 完成。",
        request=request,
    )


@dg.sensor(
    job_name=_JOB_NAME,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.INDEX_TOPIC,
        target_layer=SensorTargetLayer.RAW_SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="北京时间 18:00 起检查当前指数交易日，提交一次指数基础信息 Raw 和 Silver 更新。",
)
def index_basic_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return evaluate_index_basic_update(context, datetime.now(_TIMEZONE))
