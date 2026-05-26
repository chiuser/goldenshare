import json
from collections.abc import Mapping
from datetime import datetime

import dagster as dg

from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.sensors.readiness import (
    AssetReadinessStatus,
    CN_A_SENSOR_TIMEZONE,
    silver_index_daily_ready_for_trade_date,
)


MAX_STATUS_SAMPLE_COUNT = 20
RAW_SUCCESS_RUN_QUERY_LIMIT = 5000
INDEX_DAILY_RAW_JOB_NAME = "index_daily_update_job"
INDEX_DAILY_RAW_OP_NAME = "raw_tushare_index_daily_by_code"
DAGSTER_PARTITION_TAG = "dagster/partition"


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


def _latest_registered_trade_date(
    registered_trade_days: tuple[str, ...],
    evaluated_at: datetime,
) -> str | None:
    today = evaluated_at.date().isoformat()
    eligible_trade_days = tuple(
        trade_date for trade_date in registered_trade_days if trade_date <= today
    )
    return eligible_trade_days[-1] if eligible_trade_days else None


def _raw_update_run_config_trade_date(run_config: Mapping[str, object]) -> str | None:
    ops_config = run_config.get("ops")
    if not isinstance(ops_config, Mapping):
        return None
    raw_op_config = ops_config.get(INDEX_DAILY_RAW_OP_NAME)
    if not isinstance(raw_op_config, Mapping):
        return None
    raw_asset_config = raw_op_config.get("config")
    if not isinstance(raw_asset_config, Mapping):
        return None

    start_date = raw_asset_config.get("start_date")
    end_date = raw_asset_config.get("end_date")
    if not isinstance(start_date, str) or not isinstance(end_date, str):
        return None
    if start_date != end_date:
        return None
    return start_date


def _successful_raw_update_codes_for_trade_date(
    instance: dg.DagsterInstance,
    registered_index_codes: tuple[str, ...],
    trade_date: str,
) -> tuple[set[str], int, bool]:
    registered_code_set = set(registered_index_codes)
    tagged_successful_runs = instance.get_runs(
        filters=dg.RunsFilter(
            job_name=INDEX_DAILY_RAW_JOB_NAME,
            statuses=[dg.DagsterRunStatus.SUCCESS],
            tags={
                "asset_family": "index_daily",
                "trade_date": trade_date,
            },
        ),
        limit=RAW_SUCCESS_RUN_QUERY_LIMIT,
    )
    successful_codes = {
        index_code
        for run in tagged_successful_runs
        if (index_code := run.tags.get("index_ts_code")) in registered_code_set
    }
    missing_codes = tuple(
        index_code for index_code in registered_index_codes if index_code not in successful_codes
    )

    fallback_successful_runs = []
    if missing_codes:
        fallback_successful_runs = instance.get_runs(
            filters=dg.RunsFilter(
                job_name=INDEX_DAILY_RAW_JOB_NAME,
                statuses=[dg.DagsterRunStatus.SUCCESS],
                tags={DAGSTER_PARTITION_TAG: missing_codes},
            ),
            limit=RAW_SUCCESS_RUN_QUERY_LIMIT,
        )
        for run in fallback_successful_runs:
            index_code = run.tags.get(DAGSTER_PARTITION_TAG)
            if index_code not in registered_code_set:
                continue
            if _raw_update_run_config_trade_date(run.run_config) != trade_date:
                continue
            successful_codes.add(index_code)

    success_run_count = len(tagged_successful_runs) + len(fallback_successful_runs)
    query_limit_reached = (
        len(tagged_successful_runs) >= RAW_SUCCESS_RUN_QUERY_LIMIT
        or len(fallback_successful_runs) >= RAW_SUCCESS_RUN_QUERY_LIMIT
    )
    return successful_codes, success_run_count, query_limit_reached


def _cursor_payload(
    *,
    evaluated_at: datetime,
    target_trade_date: str | None,
    registered_trade_day_count: int,
    registered_code_count: int,
    successful_code_count: int,
    missing_success_code_count: int,
    raw_success_run_count: int,
    raw_success_run_query_limit_reached: bool,
    selected_trade_date: str | None,
    silver_status: AssetReadinessStatus | None,
    missing_success_code_samples: tuple[str, ...],
) -> str:
    payload = {
        "evaluated_at": evaluated_at.isoformat(),
        "target_trade_date": target_trade_date,
        "registered_trade_day_count": registered_trade_day_count,
        "registered_code_count": registered_code_count,
        "successful_code_count": successful_code_count,
        "missing_success_code_count": missing_success_code_count,
        "raw_success_run_count": raw_success_run_count,
        "raw_success_run_query_limit": RAW_SUCCESS_RUN_QUERY_LIMIT,
        "raw_success_run_query_limit_reached": raw_success_run_query_limit_reached,
        "selected_trade_date": selected_trade_date,
        "silver_status": _asset_status_payload(silver_status) if silver_status else None,
        "missing_success_code_samples": list(missing_success_code_samples),
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


@dg.sensor(
    job_name="silver_index_daily_update_job",
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    description="指数日线 raw-by-code 更新任务全部成功后，触发 silver 分区生成任务。",
)
def silver_index_daily_sensor(context: dg.SensorEvaluationContext) -> dg.SensorResult:
    evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
    registered_trade_days = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_index_trade_days.name))
    )
    registered_index_codes = tuple(
        sorted(context.instance.get_dynamic_partitions(cn_a_index_ts_codes.name))
    )

    if not registered_trade_days:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=None,
            registered_trade_day_count=0,
            registered_code_count=len(registered_index_codes),
            successful_code_count=0,
            missing_success_code_count=0,
            raw_success_run_count=0,
            raw_success_run_query_limit_reached=False,
            selected_trade_date=None,
            silver_status=None,
            missing_success_code_samples=(),
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
            successful_code_count=0,
            missing_success_code_count=0,
            raw_success_run_count=0,
            raw_success_run_query_limit_reached=False,
            selected_trade_date=None,
            silver_status=None,
            missing_success_code_samples=(),
        )
        return dg.SensorResult(
            skip_reason="没有注册指数代码分区，无法触发指数日线 silver 生成。",
            cursor=cursor,
        )

    target_trade_date = _latest_registered_trade_date(registered_trade_days, evaluated_at)
    if target_trade_date is None:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=None,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            successful_code_count=0,
            missing_success_code_count=0,
            raw_success_run_count=0,
            raw_success_run_query_limit_reached=False,
            selected_trade_date=None,
            silver_status=None,
            missing_success_code_samples=(),
        )
        return dg.SensorResult(
            skip_reason="没有符合当前日期窗口的指数交易日分区。",
            cursor=cursor,
        )

    silver_status = silver_index_daily_ready_for_trade_date(
        context.instance,
        target_trade_date,
    )
    if silver_status.ready:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            successful_code_count=0,
            missing_success_code_count=0,
            raw_success_run_count=0,
            raw_success_run_query_limit_reached=False,
            selected_trade_date=None,
            silver_status=silver_status,
            missing_success_code_samples=(),
        )
        return dg.SensorResult(
            skip_reason="最新指数交易日的 silver_index_daily 分区已经生成完成并通过 blocking checks。",
            cursor=cursor,
        )

    if silver_status.materialized:
        cursor = _cursor_payload(
            evaluated_at=evaluated_at,
            target_trade_date=target_trade_date,
            registered_trade_day_count=len(registered_trade_days),
            registered_code_count=len(registered_index_codes),
            successful_code_count=0,
            missing_success_code_count=0,
            raw_success_run_count=0,
            raw_success_run_query_limit_reached=False,
            selected_trade_date=None,
            silver_status=silver_status,
            missing_success_code_samples=(),
        )
        return dg.SensorResult(
            skip_reason=(
                "最新指数交易日的 silver_index_daily 已生成但 blocking checks 未全绿，"
                "暂不自动重跑，请先人工处理失败检查。"
            ),
            cursor=cursor,
        )

    successful_codes, raw_success_run_count, raw_success_run_query_limit_reached = (
        _successful_raw_update_codes_for_trade_date(
            context.instance,
            registered_index_codes,
            target_trade_date,
        )
    )
    missing_success_codes = tuple(
        index_code for index_code in registered_index_codes if index_code not in successful_codes
    )
    missing_success_code_samples = missing_success_codes[:MAX_STATUS_SAMPLE_COUNT]
    cursor = _cursor_payload(
        evaluated_at=evaluated_at,
        target_trade_date=target_trade_date,
        registered_trade_day_count=len(registered_trade_days),
        registered_code_count=len(registered_index_codes),
        successful_code_count=len(successful_codes),
        missing_success_code_count=len(missing_success_codes),
        raw_success_run_count=raw_success_run_count,
        raw_success_run_query_limit_reached=raw_success_run_query_limit_reached,
        selected_trade_date=target_trade_date if not missing_success_codes else None,
        silver_status=silver_status,
        missing_success_code_samples=missing_success_code_samples,
    )

    if missing_success_codes:
        skip_reason = "指数日线 raw update job 仍有未成功代码，暂不生成 silver。"
        if raw_success_run_query_limit_reached:
            skip_reason = (
                "指数日线 raw update job 成功记录查询达到上限且仍有未成功代码，"
                "暂不生成 silver。"
            )
        return dg.SensorResult(
            skip_reason=skip_reason,
            cursor=cursor,
        )

    return dg.SensorResult(
        run_requests=[
            dg.RunRequest(
                partition_key=target_trade_date,
                run_key=f"silver_index_daily:{target_trade_date}",
                tags={
                    "triggered_by": "silver_index_daily_sensor",
                    "asset_family": "index_daily",
                    "trade_date": target_trade_date,
                },
            )
        ],
        cursor=cursor,
    )
