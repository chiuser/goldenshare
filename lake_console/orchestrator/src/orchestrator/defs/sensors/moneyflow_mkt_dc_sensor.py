"""STOPPED, bounded market-moneyflow registration/update sensors; source I/O stays in jobs."""

from datetime import datetime

import dagster as dg
from dagster._core.storage.tags import RUN_KEY_TAG

from orchestrator.defs.asset_guards.moneyflow_mkt_dc_readiness import (
    batch_market_moneyflow_readiness,
)
from orchestrator.defs.jobs.moneyflow_mkt_dc import (
    raw_tushare_moneyflow_mkt_dc_update_job,
    silver_moneyflow_mkt_dc_update_job,
)
from orchestrator.defs.partitions import cn_a_moneyflow_mkt_dc_trade_days
from orchestrator.defs.paths import silver_trade_calendar_path
from orchestrator.defs.run_contracts.cursor_payloads import (
    build_cursor_details,
    cursor_runtime_state,
)
from orchestrator.defs.run_contracts.cursors import (
    build_sensor_cursor,
    load_sensor_cursor,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_AUTO_ATTEMPTS,
    MONEYFLOW_EVENT_RECORD_LIMIT,
    MONEYFLOW_HISTORY_MAX_DATE_FACTS,
    MONEYFLOW_MKT_HISTORY_START,
    MONEYFLOW_REGISTER_START,
    MONEYFLOW_SENSOR_INTERVAL,
    MONEYFLOW_SENSOR_START,
    MONEYFLOW_SENSOR_WINDOW,
    MoneyflowContractError,
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
from orchestrator.defs.sensors.cn_a_trade_day_sensor import (
    build_trade_day_partition_registration_result,
)
from orchestrator.defs.sensors.readiness import CN_A_SENSOR_TIMEZONE

ACTIVE = [
    dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.NOT_STARTED,
    dg.DagsterRunStatus.STARTING,
    dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
]
RAW_JOB = "raw_tushare_moneyflow_mkt_dc_update_job"
SILVER_JOB = "silver_moneyflow_mkt_dc_update_job"
PARTITIONS = cn_a_moneyflow_mkt_dc_trade_days.name


def _state(cursor):
    if cursor and len(cursor.encode()) > 8192:
        raise MoneyflowContractError("cursor_limit")
    payload = load_sensor_cursor(cursor)
    if cursor and not payload:
        raise MoneyflowContractError("cursor_invalid")
    state = cursor_runtime_state(payload.get("details", {})).get("dates", {})
    if not isinstance(state, dict) or len(state) > MONEYFLOW_SENSOR_WINDOW:
        raise MoneyflowContractError("cursor_state")
    for day, item in state.items():
        if (
            not isinstance(item, dict)
            or type(item.get("attempt", 0)) is not int
            or not 0 <= item.get("attempt", 0) <= MONEYFLOW_AUTO_ATTEMPTS
        ):
            raise MoneyflowContractError("cursor_state")
        try:
            datetime.fromisoformat(day)
        except (TypeError, ValueError) as error:
            raise MoneyflowContractError("cursor_state") from error
        for field in ("attempt_date", "verified_on"):
            if item.get(field):
                try:
                    datetime.fromisoformat(item[field])
                except (TypeError, ValueError) as error:
                    raise MoneyflowContractError("cursor_state") from error
    return state


def _failure_retryable(instance, run):
    records = instance.event_log_storage.get_records_for_run(
        run.run_id, of_type=dg.DagsterEventType.STEP_FAILURE, limit=1, ascending=False
    ).records
    if not records:
        return False
    data = records[0].event_log_entry.dagster_event.step_failure_data.user_failure_data
    value = data.metadata.get("goldenshare/retryable") if data else None
    return value is not None and value.value is True


def evaluate_market_moneyflow(context, now, *, silver=False):
    now = now.astimezone(CN_A_SENSOR_TIMEZONE)
    job_name = SILVER_JOB if silver else RAW_JOB
    name = job_name + "_sensor"
    state = _state(context.cursor)

    def result(reason, summary, *, day=None, request=None):
        cursor = build_sensor_cursor(
            evaluated_at=now,
            decision="request_runs" if request else "skip",
            target_date=day,
            selected_count=int(request is not None),
            blocked_count=int(
                reason
                not in {"request_run", "all_ready", "before_window", "empty_window"}
            ),
            details=build_cursor_details(
                sensor_name=name,
                job_name=job_name,
                asset_family="moneyflow_mkt_dc",
                partition_set=PARTITIONS,
                reason_code=reason,
                blocked_component="none" if request else "moneyflow_mkt_dc",
                summary=summary,
                next_action="等待任务完成及同日检查。"
                if request
                else "等待下次评估；错误或窗口外缺口须人工核验。",
                runtime_state={"dates": state},
            ),
        )
        return dg.SensorResult(
            run_requests=[request] if request else [],
            cursor=cursor,
            skip_reason=None if request else dg.SkipReason(summary),
        )

    if now.time().replace(tzinfo=None) < MONEYFLOW_REGISTER_START:
        return result("before_window", "尚未到上海时间22:00。")
    for job in (RAW_JOB, SILVER_JOB):
        if context.instance.get_runs(
            filters=dg.RunsFilter(job_name=job, statuses=ACTIVE), limit=1
        ):
            return result("active_run", "本表已有运行中任务。")
    root = context.resources.lake_root.root()
    context.resources.lake_root.ensure_available_for_run()
    with context.resources.duckdb.connect() as connection:
        rows = connection.execute(
            "SELECT CAST(CAST(trade_date AS DATE) AS VARCHAR) FROM read_parquet(?) "
            "WHERE exchange='SSE' AND is_open=true "
            "AND CAST(trade_date AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE) "
            "GROUP BY CAST(trade_date AS DATE) ORDER BY CAST(trade_date AS DATE) DESC LIMIT ?",
            [
                str(silver_trade_calendar_path(root)),
                MONEYFLOW_SENSOR_START,
                now.date().isoformat(),
                MONEYFLOW_SENSOR_WINDOW,
            ],
        ).fetchall()
        dates = tuple(str(row[0]) for row in reversed(rows))
    if not dates:
        return result("empty_window", "当前没有历史截止日后的应更新交易日。")
    state = {day: state[day] for day in dates if day in state}
    registered = context.instance.get_dynamic_partitions(PARTITIONS)
    if len(registered) > MONEYFLOW_HISTORY_MAX_DATE_FACTS:
        return result("partition_limit", "专属分区数量超过已批准上限。")
    missing = next((day for day in dates if day not in registered), None)
    if missing:
        return result(
            "missing_partition", "窗口有未注册交易日，等待注册器。", day=missing
        )
    try:
        statuses = batch_market_moneyflow_readiness(
            context.instance,
            root,
            dates,
            layers=("raw", "silver") if silver else ("raw",),
        )
    except MoneyflowContractError as error:
        return result(str(error), "交付证据不足以在预算内判断就绪。")
    current = statuses["silver" if silver else "raw"]
    blocked = next(
        (
            day
            for day in dates
            if current[day].reason
            not in (
                {
                    "ready",
                    "missing_materialization",
                    "upstream_revision",
                    "raw_not_ready",
                }
                if silver
                else {"ready", "missing_materialization"}
            )
        ),
        None,
    )
    if blocked:
        return result(
            current[blocked].reason,
            "已有文件或检查需要人工处理，不自动重跑。",
            day=blocked,
        )
    order = sorted(dates, key=lambda day: (day != now.date().isoformat(), day))
    if silver:
        selected = next(
            (
                day
                for day in order
                if statuses["raw"][day].ready
                and current[day].reason
                in {"missing_materialization", "upstream_revision"}
            ),
            None,
        )
        if selected is None:
            return result(
                "all_ready"
                if all(s.ready for s in current.values())
                else "raw_not_ready",
                "Silver已齐备，或等待对应Raw就绪。",
            )
        digest = statuses["raw"][selected].metadata["file_sha256"]
        request = build_run_request(
            run_key=build_asset_update_run_key(
                subject="silver_moneyflow_mkt_dc", unit_id=selected + ":" + digest
            ),
            partition_key=selected,
        )
    else:
        for day in dates:
            status = current[day]
            if (
                status.ready
                and datetime.fromtimestamp(
                    status.record.timestamp, CN_A_SENSOR_TIMEZONE
                ).date()
                == now.date()
            ):
                state.setdefault(day, {})["verified_on"] = now.date().isoformat()
        selected = next((day for day in order if not current[day].ready), None)
        if selected is None:
            selected = next(
                (
                    day
                    for day in order
                    if state.get(day, {}).get("verified_on") != now.date().isoformat()
                ),
                None,
            )
        if selected is None:
            return result("all_ready", "窗口已齐备且今日已复核。")
        item = state.setdefault(selected, {})
        records = context.instance.get_run_records(
            filters=dg.RunsFilter(
                job_name=RAW_JOB, tags={"dagster/partition": selected}
            ),
            limit=MONEYFLOW_EVENT_RECORD_LIMIT,
            order_by="create_timestamp",
        )
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if (
            len(records) >= MONEYFLOW_EVENT_RECORD_LIMIT
            and records[-1].create_timestamp.timestamp() >= midnight.timestamp()
        ):
            return result(
                "run_record_limit", "运行记录达到查询上限，停止自动判断。", day=selected
            )
        latest = records[0].dagster_run if records else None
        if (
            latest
            and latest.status
            in {dg.DagsterRunStatus.FAILURE, dg.DagsterRunStatus.CANCELED}
            and not _failure_retryable(context.instance, latest)
        ):
            return result(
                "non_retryable_failure",
                "最近任务失败未被明确标记为临时源错误。",
                day=selected,
            )
        # Persistent run identities are authoritative. A lost cursor cannot reset
        # the six keys, and an unconsumed request is replayed with the same key.
        keys = [
            build_repair_attempt_run_key(
                subject="raw_tushare_moneyflow_mkt_dc",
                repair_scope_id=selected,
                attempt=n,
                attempt_scope=now.date().isoformat(),
            )
            for n in range(1, MONEYFLOW_AUTO_ATTEMPTS + 1)
        ]
        used = {r.dagster_run.tags.get(RUN_KEY_TAG) for r in records}
        attempt = next((n for n, key in enumerate(keys, 1) if key not in used), None)
        if attempt is None:
            return result(
                "attempt_limit",
                "本交易日在今日已达到六次自动尝试，等待复核。",
                day=selected,
            )
        item.update(attempt=attempt, attempt_date=now.date().isoformat())
        request = build_run_request(
            run_key=build_repair_attempt_run_key(
                subject="raw_tushare_moneyflow_mkt_dc",
                repair_scope_id=selected,
                attempt=attempt,
                attempt_scope=now.date().isoformat(),
            ),
            partition_key=selected,
        )
    return result(
        "request_run",
        "同日证据已核对，提交一个资金流任务。",
        day=selected,
        request=request,
    )


@dg.sensor(
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=MONEYFLOW_SENSOR_INTERVAL,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.PARTITION,
        role=SensorRole.PARTITION_REGISTRATION,
    ),
    description="上海22:00后优先登记大盘资金流当日，最多补一个历史漏登记日，不提交job。",
)
def cn_a_moneyflow_mkt_dc_trade_day_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    result = build_trade_day_partition_registration_result(
        context,
        dynamic_partitions=cn_a_moneyflow_mkt_dc_trade_days,
        min_trade_date=MONEYFLOW_MKT_HISTORY_START,
        partition_set_label="东方财富大盘资金流向",
        same_day_register_start=MONEYFLOW_REGISTER_START,
        sensor_name="cn_a_moneyflow_mkt_dc_trade_day_sensor",
        asset_family="moneyflow_mkt_dc",
        cursor_partition_set=PARTITIONS,
    )
    payload = load_sensor_cursor(result.cursor)
    details = payload["details"]
    frontier = details.get("frontier", {})
    if (
        details.get("evidence", {}).get("eligible_open_day_count", 0)
        > MONEYFLOW_HISTORY_MAX_DATE_FACTS
    ):
        raise MoneyflowContractError("partition_limit")
    today = frontier.get("today")
    registered = context.instance.get_dynamic_partitions(PARTITIONS)
    if len(registered) > MONEYFLOW_HISTORY_MAX_DATE_FACTS:
        raise MoneyflowContractError("partition_limit")
    if (
        frontier.get("today_is_open")
        and frontier.get("same_day_register_window_started")
        and today not in registered
    ):
        selected = [today] + [day for day in payload["sample_keys"] if day != today][:1]
        payload["selected_count"] = len(selected)
        details["summary"] = "本次优先登记当日，再补最早漏登记日。"
        return dg.SensorResult(
            dynamic_partitions_requests=[
                cn_a_moneyflow_mkt_dc_trade_days.build_add_request(selected)
            ],
            cursor=build_sensor_cursor(
                evaluated_at=datetime.fromisoformat(payload["evaluated_at"]),
                decision="register_partitions",
                target_date=today,
                selected_count=len(selected),
                blocked_count=max(
                    0, details["evidence"]["unregistered_count"] - len(selected)
                ),
                sample_keys=selected,
                details=details,
            ),
        )
    return result


@dg.sensor(
    job=raw_tushare_moneyflow_mkt_dc_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=MONEYFLOW_SENSOR_INTERVAL,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="22:00后最近10日一次提交一日Raw，临时源错误有限重试，每日最多复核一次。",
)
def raw_tushare_moneyflow_mkt_dc_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return evaluate_market_moneyflow(context, datetime.now(CN_A_SENSOR_TIMEZONE))


@dg.sensor(
    job=silver_moneyflow_mkt_dc_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=MONEYFLOW_SENSOR_INTERVAL,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="同日已绿Raw产生新hash后一次提交一日Silver，不请求源。",
)
def silver_moneyflow_mkt_dc_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return evaluate_market_moneyflow(
        context, datetime.now(CN_A_SENSOR_TIMEZONE), silver=True
    )
