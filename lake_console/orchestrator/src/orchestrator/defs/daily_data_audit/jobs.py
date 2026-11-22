from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

import dagster as dg
import duckdb
from pydantic import Field
from sqlalchemy.exc import SQLAlchemyError

from orchestrator.defs.daily_data_audit.evidence import (
    BUSINESS_DATE_TAG,
    SHANGHAI,
    SUMMARY_JOB,
    SUMMARY_META,
    load_evidence,
    read_summary,
)
from orchestrator.defs.daily_data_audit.registry import read_calendar, targets_for_day
from orchestrator.defs.daily_data_audit.summary import ETF_DAILY_INPUTS, make_summary
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key


class SummaryConfig(dg.Config):
    business_date: str
    changed_asset_keys: list[str] = Field(default_factory=list)


@dg.op(out=dg.Out(dg.Nothing))
def generate_data_audit_summary(
    context: dg.OpExecutionContext, config: SummaryConfig
) -> None:
    day = date.fromisoformat(config.business_date)
    observed_at = datetime.now(SHANGHAI)
    context.instance.add_run_tags(context.run_id, {BUSINESS_DATE_TAG: day.isoformat()})
    try:
        calendar = read_calendar(Path(DEFAULT_LAKE_ROOT), day)
    except (OSError, duckdb.Error) as error:
        context.log.warning(f"交易日历暂不可读取: {error}")
        calendar = {}
    targets = targets_for_day(day, calendar)
    previous = (
        read_summary(context.instance, day) if config.changed_asset_keys else None
    )
    changed = set(config.changed_asset_keys) if previous else set()
    for silver, raw in ETF_DAILY_INPUTS.items():
        if changed.intersection({silver, raw}):
            changed.update({silver, raw})
    selected = tuple(
        target for target in targets if not changed or target.asset_key in changed
    )
    evidence = {}
    try:
        evidence = load_evidence(context.instance, selected, day, observed_at)
    except SQLAlchemyError as error:
        context.log.warning(f"产出和 Check 记录暂不可读取: {error}")
    result = make_summary(day, observed_at, targets, evidence, previous, changed)
    context.add_output_metadata({SUMMARY_META: dg.MetadataValue.json(result)})


@dg.job(name=SUMMARY_JOB)
def daily_data_audit_summary_job():
    generate_data_audit_summary()


def _request(
    day: date, run_key: str, changed: list[str] | None = None
) -> dg.RunRequest:
    return dg.RunRequest(
        run_key=build_asset_update_run_key(subject=SUMMARY_JOB, unit_id=run_key),
        tags={BUSINESS_DATE_TAG: day.isoformat()},
        run_config=dg.RunConfig(
            ops={
                "generate_data_audit_summary": SummaryConfig(
                    business_date=day.isoformat(),
                    changed_asset_keys=changed or [],
                )
            },
        ),
    )


@dg.schedule(
    job=daily_data_audit_summary_job,
    cron_schedule="0 0 * * *",
    execution_timezone="Asia/Shanghai",
    default_status=dg.DefaultScheduleStatus.STOPPED,
)
def daily_data_audit_summary_schedule(
    context: dg.ScheduleEvaluationContext,
) -> dg.RunRequest:
    local_date = context.scheduled_execution_time.astimezone(SHANGHAI).date()
    day = local_date - timedelta(days=1)
    return _request(day, day.isoformat())


@dg.sensor(
    job=daily_data_audit_summary_job, default_status=dg.DefaultSensorStatus.STOPPED
)
def daily_data_audit_summary_refresh_sensor(context: dg.SensorEvaluationContext):
    observed_at = datetime.now(SHANGHAI)
    day = observed_at.date() - timedelta(days=1)
    summary = read_summary(context.instance, day)
    if summary is None:
        return dg.SkipReason("所选日尚无每日总结")
    rows = {row["scope"]["asset_key"]: row for row in summary["rows"]}
    targets = tuple(
        replace(target, partition=rows[target.asset_key]["scope"]["partition_key"])
        for target in targets_for_day(day, {})
        if target.asset_key in rows
    )
    evidence = load_evidence(context.instance, targets, day, observed_at)
    changed = set()
    latest_event = 0.0
    for key, current in evidence.items():
        materialization = current.materialization
        if materialization is None:
            continue
        row_time = datetime.fromisoformat(rows[key]["observed_at"]).timestamp()
        event_time = max(
            [
                materialization.timestamp,
                *(check.event.timestamp for check in current.checks.values()),
            ]
        )
        if event_time > row_time:
            changed.add(key)
            latest_event = max(latest_event, event_time)
    if not changed:
        return dg.SkipReason("没有晚到产出或 Check")
    graph = context.repository_def.asset_graph
    pending = [dg.AssetKey(key) for key in changed if graph.has(dg.AssetKey(key))]
    while pending:
        for child in graph.get_children(graph.get(pending.pop())):
            key = child.key.to_user_string()
            if key in rows and key not in changed:
                pending.append(child.key)
                changed.add(key)
    return _request(day, f"{day.isoformat()}-{latest_event}", sorted(changed))
