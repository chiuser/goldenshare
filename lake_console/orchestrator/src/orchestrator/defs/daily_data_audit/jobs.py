import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

import dagster as dg
import duckdb
from pydantic import Field
from sqlalchemy.exc import SQLAlchemyError

from orchestrator.defs.daily_data_audit.board_refresh import next_board_refresh
from orchestrator.defs.daily_data_audit.board_summary import (
    BOARD_CHECKS,
    RAW_CLASSIFICATION,
    apply_board_summary,
)
from orchestrator.defs.daily_data_audit.dc_index_review import (
    BASELINE_DAY,
    read_board_review,
    read_dc_index_standard,
)
from orchestrator.defs.daily_data_audit.evidence import (
    AUDIT_ASSET_TAG,
    AUDIT_PUBLICATION_TAG,
    BUSINESS_DATE_TAG,
    INDEX_MINUTE_JOB,
    SHANGHAI,
    SUMMARY_JOB,
    SUMMARY_META,
    load_evidence,
    read_summary,
)
from orchestrator.defs.daily_data_audit.index_minute_audit import (
    INDEX_MINUTE_ASSETS,
    SILVER_INPUTS,
    matching_index_minute_result,
)
from orchestrator.defs.daily_data_audit.registry import read_calendar, targets_for_day
from orchestrator.defs.daily_data_audit.summary import (
    ETF_DAILY_INPUTS,
    MACD_KDJ_INDICATOR_INPUTS,
    MACD_KDJ_STATE_INPUTS,
    MONEYFLOW_SILVER_INPUTS,
    STOCK_BASIC_RAW,
    STOCK_DAILY_QFQ_GOLD,
    STOCK_DAILY_SILVER,
    STOCK_MINUTE_QFQ_INPUTS,
    STOCK_MINUTE_SILVER_INPUTS,
    make_summary,
    stock_daily_checks_passed,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, gold_stock_daily_qfq_path
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key


class SummaryConfig(dg.Config):
    business_date: str
    changed_asset_keys: list[str] = Field(default_factory=list)
    board_confirmation_run_id: str | None = None
    board_recheck_run_id: str | None = None
    use_board_history: bool = False


STOCK_SNAPSHOT_INPUTS = {
    "silver_stock_basic": (STOCK_BASIC_RAW,),
    "silver_stock_lifecycle": (STOCK_BASIC_RAW,),
    "silver_namechange": ("raw_tushare_namechange", "silver_stock_basic"),
    "silver_stock_identity_map": ("silver_stock_lifecycle", "silver_namechange"),
}


def _board_review(instance, day, previous_trade_date, evidence, *, use_history=False, historical_candidate=None):
    return read_board_review(
        instance, day, previous_trade_date=previous_trade_date,
        raw_evidence=evidence.get(RAW_CLASSIFICATION),
        use_history=use_history,
        lake_root=Path(DEFAULT_LAKE_ROOT),
        historical_candidate=historical_candidate,
    )


def _refresh_board_summary(instance, day, observed_at, previous, config):
    previous_review = None
    if config.board_confirmation_run_id:
        standard = read_dc_index_standard(instance, day)
        if not standard or standard["version"] != config.board_confirmation_run_id:
            raise dg.Failure("所用东方财富板块分类标准集已变更")
        reference = (
            instance.get_run_by_id(standard["reference_version"])
            if standard["reference_version"] else None
        )
        previous_date = date.fromisoformat(reference.tags[BUSINESS_DATE_TAG]) if reference else None
    else:
        previous_review = next(
            row["board_review"] for row in previous["rows"]
            if row["scope"]["asset_key"] == RAW_CLASSIFICATION and "board_review" in row
        )
        reference = previous_review["reference"]
        previous_date = date.fromisoformat(reference["business_date"]) if reference else None
    changed = set(config.changed_asset_keys).intersection(BOARD_CHECKS)
    read_keys = changed | {RAW_CLASSIFICATION}
    targets = tuple(
        target for target in targets_for_day(day, {day: True})
        if target.asset_key in read_keys
    )
    evidence = load_evidence(instance, targets, day, observed_at)
    review = _board_review(instance, day, previous_date, evidence, historical_candidate=previous_review)
    if config.board_recheck_run_id and (
        review["standard"] or (review["recheck"] or {}).get("run_id") != config.board_recheck_run_id
    ):
        raise dg.Failure("所用东方财富板块复核结果已变更")
    report = {
        **previous,
        "observed_at": observed_at.isoformat(),
        "generated_at": datetime.now(SHANGHAI).isoformat(),
    }
    return apply_board_summary(report, evidence, review, review["standard"], changed)


@dg.op(out=dg.Out(dg.Nothing))
def generate_data_audit_summary(
    context: dg.OpExecutionContext, config: SummaryConfig
) -> None:
    day = date.fromisoformat(config.business_date)
    if config.use_board_history and day < BASELINE_DAY:
        raise dg.Failure("东方财富板块分类历史接续从 2026-11-19 开始")
    observed_at = datetime.now(SHANGHAI)
    context.instance.add_run_tags(context.run_id, {BUSINESS_DATE_TAG: day.isoformat()})
    previous = read_summary(context.instance, day) if config.changed_asset_keys or config.use_board_history else None
    if (config.board_confirmation_run_id or config.board_recheck_run_id) and previous:
        result = _refresh_board_summary(
            context.instance, day, observed_at, previous, config,
        )
        context.add_output_metadata({SUMMARY_META: dg.MetadataValue.json(result)})
        return
    try:
        calendar = read_calendar(Path(DEFAULT_LAKE_ROOT), day)
    except (OSError, duckdb.Error) as error:
        context.log.warning(f"交易日历暂不可读取: {error}")
        calendar = {}
    targets = targets_for_day(day, calendar)
    changed = set(config.changed_asset_keys) if previous else set()
    if config.use_board_history and previous:
        changed.add(RAW_CLASSIFICATION)
    for silver, raw in ETF_DAILY_INPUTS.items():
        if changed.intersection({silver, raw}):
            changed.update({silver, raw})
    changed.update(
        silver for silver, raw in MONEYFLOW_SILVER_INPUTS.items() if raw in changed
    )
    for key, inputs in STOCK_SNAPSHOT_INPUTS.items():
        if changed.intersection(inputs):
            changed.add(key)
    if STOCK_DAILY_SILVER in changed:
        changed.add(STOCK_DAILY_QFQ_GOLD)
        changed.update(STOCK_MINUTE_SILVER_INPUTS)
    changed.update(
        key
        for key, sources in STOCK_MINUTE_SILVER_INPUTS.items()
        if changed.intersection(sources)
    )
    changed.update(
        key for key, source in STOCK_MINUTE_QFQ_INPUTS.items() if source in changed
    )
    changed.update(
        key for key, source in MACD_KDJ_INDICATOR_INPUTS.items() if source in changed
    )
    changed.update(
        key for key, source in MACD_KDJ_STATE_INPUTS.items() if source in changed
    )
    minute_input_by_asset = {
        row["scope"]["asset_key"]: {item["asset_key"] for item in row["version"]["inputs"]}
        for row in previous["rows"] if row["scope"]["asset_key"] in SILVER_INPUTS
    } if previous else {}
    for silver, source in SILVER_INPUTS.items():
        inputs = minute_input_by_asset.get(silver) or {source}
        if changed.intersection(inputs):
            changed.add(silver)
    board_changes = set(BOARD_CHECKS) if not changed else changed.intersection(BOARD_CHECKS)
    if RAW_CLASSIFICATION in changed and previous.get("board_standard_version"):
        board_changes = set(BOARD_CHECKS)
    read_keys = changed | board_changes if changed else set()
    if board_changes and changed:
        read_keys.add(RAW_CLASSIFICATION)
    if STOCK_DAILY_QFQ_GOLD in changed or changed.intersection(
        STOCK_MINUTE_SILVER_INPUTS
    ):
        read_keys.add(STOCK_DAILY_SILVER)
    selected = tuple(
        target for target in targets if not changed or target.asset_key in read_keys
    )
    evidence = {}
    previous_stock_basic = None
    try:
        evidence = load_evidence(context.instance, selected, day, observed_at)
        if STOCK_BASIC_RAW in evidence and calendar.get(day):
            previous_day = max(
                (
                    day_key
                    for day_key, is_open in calendar.items()
                    if is_open and day_key < day
                ),
                default=None,
            )
            if previous_day:
                target = next(
                    target for target in selected if target.asset_key == STOCK_BASIC_RAW
                )
                previous_stock_basic = load_evidence(
                    context.instance,
                    (replace(target, expected_date=previous_day),),
                    previous_day,
                    observed_at,
                ).get(STOCK_BASIC_RAW)
    except SQLAlchemyError as error:
        context.log.warning(f"产出和 Check 记录暂不可读取: {error}")
    qfq_run_ids = {
        key: bundle.materialization.run_id
        for key, bundle in evidence.items()
        if bundle.materialization
        and (key == STOCK_DAILY_QFQ_GOLD or key in STOCK_MINUTE_QFQ_INPUTS)
    }
    successful_deliveries = set()
    if qfq_run_ids:
        try:
            run_ids = sorted(set(qfq_run_ids.values()))
            successful_run_ids = {
                run.run_id
                for run in context.instance.get_runs(
                    filters=dg.RunsFilter(
                        run_ids=run_ids, statuses=[dg.DagsterRunStatus.SUCCESS]
                    ),
                    limit=len(run_ids),
                )
            }
            successful_deliveries = {
                key
                for key, run_id in qfq_run_ids.items()
                if run_id in successful_run_ids
            }
        except SQLAlchemyError as error:
            context.log.warning(f"前复权任务终态暂不可读取: {error}")
    file_exists = None
    if stock_daily_checks_passed(evidence) and any(
        target.asset_key == STOCK_DAILY_QFQ_GOLD and target.requires_update
        for target in selected
    ):
        try:
            file_exists = gold_stock_daily_qfq_path(
                Path(DEFAULT_LAKE_ROOT), day.isoformat()
            ).is_file()
        except OSError as error:
            context.log.warning(f"前复权日线文件存在情况暂无法确认: {error}")
    minute_results = {}
    identities = {}
    for target in selected:
        key = target.asset_key
        if key not in INDEX_MINUTE_ASSETS or target.excluded_reason or (changed and key not in changed):
            continue
        bundle = evidence.get(key)
        try:
            minute_results[key] = matching_index_minute_result(
                context.instance, key, day, bundle.materialization if bundle else None,
                observed_at, Path(DEFAULT_LAKE_ROOT), identities,
            )
        except SQLAlchemyError as error:
            context.log.warning(f"{key} 独立审计结果暂不可读取: {error}")
            minute_results[key] = None
    result = make_summary(
        day,
        observed_at,
        targets,
        evidence,
        previous,
        changed,
        stock_daily_qfq_file_exists=file_exists,
        qfq_successful_deliveries=successful_deliveries,
        previous_stock_basic=previous_stock_basic,
        index_minute_results=minute_results,
    )
    if board_changes and any(
        target.asset_key in board_changes and not target.excluded_reason for target in selected
    ):
        previous_trade_date = max(
            (candidate for candidate, is_open in calendar.items() if candidate < day and is_open),
            default=None,
        )
        review = _board_review(
            context.instance, day, previous_trade_date, evidence,
            use_history=config.use_board_history,
        )
        result = apply_board_summary(result, evidence, review, review["standard"], board_changes)
    context.add_output_metadata({SUMMARY_META: dg.MetadataValue.json(result)})


@dg.job(name=SUMMARY_JOB)
def daily_data_audit_summary_job():
    generate_data_audit_summary()


def _request(
    day: date, run_key: str, changed: list[str] | None = None,
    *, board_confirmation_run_id: str | None = None,
    board_recheck_run_id: str | None = None,
) -> dg.RunRequest:
    return dg.RunRequest(
        run_key=build_asset_update_run_key(subject=SUMMARY_JOB, unit_id=run_key),
        tags={BUSINESS_DATE_TAG: day.isoformat()},
        run_config=dg.RunConfig(
            ops={
                "generate_data_audit_summary": SummaryConfig(
                    business_date=day.isoformat(),
                    changed_asset_keys=changed or [],
                    board_confirmation_run_id=board_confirmation_run_id,
                    board_recheck_run_id=board_recheck_run_id,
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


def _minute_result_refresh(instance, cursor, observed_at):
    state = json.loads(cursor)
    after = state.get("index_minute_after")
    records = instance.get_run_records(
        filters=dg.RunsFilter(
            job_name=INDEX_MINUTE_JOB, statuses=[dg.DagsterRunStatus.SUCCESS],
            updated_after=datetime.fromisoformat(after) if after else None,
        ),
        order_by="update_timestamp", ascending=True, limit=1,
    )
    if not records:
        return None, cursor
    record = records[0]
    state["index_minute_after"] = record.update_timestamp.isoformat()
    cursor = json.dumps(state)
    run = record.dagster_run
    asset = run.tags.get(AUDIT_ASSET_TAG)
    publication_run = run.tags.get(AUDIT_PUBLICATION_TAG)
    if asset not in INDEX_MINUTE_ASSETS or not publication_run:
        return None, cursor
    day = date.fromisoformat(run.tags[BUSINESS_DATE_TAG])
    report = read_summary(instance, day)
    if not report:
        return None, cursor
    row = next(row for row in report["rows"] if row["scope"]["asset_key"] == asset)
    if record.update_timestamp <= datetime.fromisoformat(row["observed_at"]):
        return None, cursor
    targets = tuple(target for target in targets_for_day(day, {day: True}) if target.asset_key == asset)
    delivery = load_evidence(instance, targets, day, observed_at).get(asset)
    if not (delivery and delivery.materialization and delivery.materialization.run_id == publication_run):
        return None, cursor
    return _request(day, f"index-minute:{day}:{run.run_id}", [asset]), cursor


@dg.sensor(
    job=daily_data_audit_summary_job, default_status=dg.DefaultSensorStatus.STOPPED
)
def daily_data_audit_summary_refresh_sensor(context: dg.SensorEvaluationContext):
    observed_at = datetime.now(SHANGHAI)
    board, cursor = next_board_refresh(context.instance, context.cursor, observed_at)
    if board:
        return dg.SensorResult(
            cursor=cursor,
            run_requests=[_request(
                board.day, board.unit_id, list(board.assets),
                board_confirmation_run_id=board.standard_version,
                board_recheck_run_id=board.recheck_run_id,
            )],
        )
    minute, cursor = _minute_result_refresh(context.instance, cursor, observed_at)
    if minute:
        return dg.SensorResult(cursor=cursor, run_requests=[minute])
    day = observed_at.date() - timedelta(days=1)
    summary = read_summary(context.instance, day)
    if summary is None:
        return dg.SensorResult(skip_reason="所选日尚无每日总结", cursor=cursor)
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
                *(
                    check.event.timestamp
                    for check in current.checks.values()
                    if not (key in BOARD_CHECKS and summary.get("board_standard_version"))
                ),
            ]
        )
        if event_time > row_time:
            changed.add(key)
            latest_event = max(latest_event, event_time)
    if not changed:
        return dg.SensorResult(skip_reason="没有晚到产出或 Check", cursor=cursor)
    graph = context.repository_def.asset_graph
    pending = [dg.AssetKey(key) for key in changed if graph.has(dg.AssetKey(key))]
    while pending:
        for child in graph.get_children(graph.get(pending.pop())):
            key = child.key.to_user_string()
            if key in rows and key not in changed:
                pending.append(child.key)
                changed.add(key)
    return dg.SensorResult(
        run_requests=[_request(day, f"{day.isoformat()}-{latest_event}", sorted(changed))],
        cursor=cursor,
    )
