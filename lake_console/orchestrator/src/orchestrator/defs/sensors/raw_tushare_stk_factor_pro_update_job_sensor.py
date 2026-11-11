"""Current-trade-day stock technical factor admission; stopped by default."""

from datetime import datetime
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.asset_guards import stk_factor_pro_readiness as R
from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_records import (
    resource_cleanup,
)
from orchestrator.defs.checks.stk_factor_pro import factor_known_file_sha
from orchestrator.defs.jobs.stk_factor_pro import raw_tushare_stk_factor_pro_update_job
from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT, raw_adj_factor_path
from orchestrator.defs.run_contracts import stk_factor_pro as C
from orchestrator.defs.run_contracts.cursors import (
    SensorCursorDecision,
    build_sensor_cursor,
    load_sensor_cursor,
    sensor_cursor_details,
)
from orchestrator.defs.run_contracts.run_keys import build_asset_update_run_key
from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
    build_sensor_tags,
)
from orchestrator.defs.source_readiness.stk_factor_pro import (
    probe_stk_factor_pro_source,
)
from orchestrator.tushare_download import DownloadControl
from orchestrator.tushare_download.configuration import ConfigurationLoader
from orchestrator.tushare_download.source_transport import SystemClock


def _now():
    return datetime.now(ZoneInfo(C.STK_FACTOR_PRO_TIMEZONE))


def _slot(now):
    return (
        (now.hour * 60 + now.minute - C.STK_FACTOR_PRO_FIRST_SLOT_HOUR * 60)
        // C.STK_FACTOR_PRO_SLOT_MINUTES
        if now.hour >= C.STK_FACTOR_PRO_FIRST_SLOT_HOUR
        else None
    )


def _result(
    now, day, previous_slot, message, *, probed=None, request=None, details=None
):
    return dg.SensorResult(
        run_requests=[request] if request is not None else [],
        skip_reason=None if request is not None else message,
        cursor=build_sensor_cursor(
            evaluated_at=now,
            decision=SensorCursorDecision.REQUEST_RUNS
            if request is not None
            else SensorCursorDecision.SKIP,
            target_date=str(day),
            selected_count=int(request is not None),
            details={
                "execution_day": str(day),
                "last_probed_slot": previous_slot if probed is None else probed,
                "summary": message,
                "next_action": "按当前合法时点及上游结果继续评估。",
                **(details or {}),
            },
        ),
    )


def _previous(connection, lake, day, inherited, known_records):
    fact = R._load_basis(
        connection,
        path=R._GLOBALS["calendar"][0](lake),
        kind="calendar",
        trade_date=None,
        basis_inputs={"files": inherited},
        known_records=known_records,
    )
    if not fact["basis"].valid:
        return None, fact["reason"]
    rows = connection.execute(
        f"SELECT t.is_open,p.trade_date FROM {fact['relation']} t LEFT JOIN {fact['relation']} p "
        "ON p.exchange='SSE' AND p.trade_date=t.pretrade_date AND p.trade_date<t.trade_date AND p.is_open "
        "WHERE t.exchange='SSE' AND t.trade_date=?",
        [day],
    ).fetchall()
    if len(rows) != 1 or rows[0][0] is None:
        return None, "SSE日历无法确认当天。"
    if not rows[0][0]:
        return None, "当天休市。"
    if rows[0][1] is None:
        return None, "SSE日历缺pretrade_date所指的上一开市日。"
    return rows[0][1], ""


def _history_complete(instance, prior, known_pg):
    if (
        prior.pending_plan_refs
        or prior.unresolved_day_failure_run_id
        or prior.unresolved_history_failure_run_id
        or prior.history_result_ref is None
    ):
        return False
    values = R._stk_factor_pro_exact_observation(
        instance,
        prior.history_result_ref,
        target=prior.target_trade_date,
        phase="history",
        known_pg=known_pg,
    )
    return (
        values["result"] in ("completed", "no_action")
        and R.read_stk_factor_pro_run(
            instance, prior.history_result_ref.run_id, known_pg=known_pg
        ).status
        == dg.DagsterRunStatus.SUCCESS
    )


def _probe_details(connection, probe):
    result = {
        "source_row_count": probe.source_row_count,
        "source_code_count": probe.source_code_count,
        "request_count": probe.request_count,
        "page_count": probe.page_count,
        "elapsed_ms": probe.elapsed_ms,
        "optional_count": probe.optional_count,
        "optional_present_count": probe.optional_present_count,
        "error_code": probe.error_code.name if probe.error_code is not None else None,
    }
    counts = probe.coverage_counts
    if counts is not None:
        result.update(
            {
                name: getattr(counts, name)
                for name in (
                    "expected_count",
                    "actual_count",
                    "missing_count",
                    "extra_count",
                )
            }
        )
        if counts.expected_count is not None:
            for kind in ("missing", "extra"):
                if getattr(counts, kind + "_count"):
                    result[kind + "_sample_codes"] = [
                        row[0]
                        for row in connection.execute(
                            f"SELECT ts_code FROM stk_factor_pro_coverage_{kind} ORDER BY ts_code LIMIT 20"
                        ).fetchall()
                    ]
    return result


def evaluate_stk_factor_pro_update(context):
    now = _now()
    day, slot = now.date(), _slot(now)
    saved = sensor_cursor_details(load_sensor_cursor(context.cursor))
    last = (
        saved.get("last_probed_slot")
        if saved.get("execution_day") == str(day)
        else None
    )
    if slot is None:
        return _result(now, day, last, "等待上海19:00至午夜自动窗口。")
    context.resources.lake_root.ensure_available_for_run()
    lake = context.resources.lake_root.root()
    inherited, known_records, known_pg = {}, {}, {}
    with (
        context.resources.duckdb.connect() as connection,
        resource_cleanup(
            lambda: R.release_stk_factor_pro_coverage_inputs(
                connection, inherited_facts=inherited
            )
        ),
    ):
        previous, reason = _previous(connection, lake, day, inherited, known_records)
        if previous is None:
            return _result(now, day, last, reason)
        if not context.instance.has_dynamic_partition(
            C.STK_FACTOR_PRO_PARTITIONS, str(day)
        ):
            return _result(now, day, last, "等待目标交易日分区登记。")
        unit = f"{day.isoformat()}/{day.isoformat()}/{slot}"
        submitted = context.instance.get_run_records(
            filters=C.build_stk_factor_pro_sensor_run_filter(
                run_key=build_asset_update_run_key(
                    subject=C.STK_FACTOR_PRO_UPDATE_JOB_NAME, unit_id=unit
                )
            ),
            limit=1,
        )
        if submitted:
            return _result(now, day, last, "当前时点已有持久任务，等待下一合法时点。")
        active = R.read_stk_factor_pro_other_active_runs(context.instance)
        if active:
            return _result(now, day, last, "存在活动日更或历史repair，暂不提交。")
        if last == slot:
            return _result(now, day, last, "当前时点已经探测源端，等待下一合法时点。")
        prior = R.read_stk_factor_pro_recorded_results(
            context.instance, target_trade_date=day, known_pg=known_pg
        )
        for failed in (
            prior.unresolved_day_failure_run_id,
            prior.unresolved_history_failure_run_id,
        ):
            if (
                failed
                and not R.read_stk_factor_pro_failure(
                    context.instance, failed, known_pg=known_pg
                )["retryable"]
            ):
                return _result(now, day, last, "原任务不可自动重试，等待管理员处理。")
        upstream = R.read_stk_factor_pro_upstream_status(
            context.instance,
            target_trade_date=day,
            previous_trade_date=previous,
            known_pg=known_pg,
        )
        if not upstream.ready:
            return _result(now, day, last, upstream.reason)
        published = R.read_stk_factor_pro_day_publication(
            context.instance, prior=prior, lake_root=lake, known_pg=known_pg
        )
        if published is not None and _history_complete(
            context.instance, prior, known_pg
        ):
            baseline = R.read_stk_factor_pro_day_plan_factor_shas(
                day_observation=published[0],
                publication_checks=published[1],
                previous_trade_date=previous,
                staging_root=DEFAULT_LAKE_STAGING_ROOT,
                contract=C.ContractIdentity(
                    "stk_factor_pro",
                    "1",
                    C.STK_FACTOR_PRO_CONTRACT_CONTENT_DIGEST,
                    C.STK_FACTOR_PRO_PROCESSING_VERSION,
                ),
                known_records=known_records,
            )
            current = tuple(
                factor_known_file_sha(
                    raw_adj_factor_path(lake, str(d)), known_records=known_records
                )
                for d in (day, previous)
            )
            if current == baseline:
                return _result(
                    now, day, last, "当天两层及历史已完成，股票复权因子摘要未变。"
                )
        inputs = R.prepare_stk_factor_pro_coverage_inputs(
            connection,
            lake_root=lake,
            trade_date=day,
            inherited_facts=inherited,
            known_records=known_records,
        )
        if inputs["unknown_input_kinds"] or inputs["is_open"] is not True:
            return _result(now, day, last, inputs["reason"] or "覆盖依据尚未就绪。")
        probe = probe_stk_factor_pro_source(
            connection,
            target_trade_date=day,
            coverage_inputs=inputs,
            config=ConfigurationLoader.load_configuration(),
            clock=SystemClock(),
            control=DownloadControl(),
        )
        details = _probe_details(connection, probe)
        finished = _now()
        if finished.date() != day or _slot(finished) != slot:
            return _result(
                finished,
                day,
                last,
                "源探测跨出原时点，本轮不提交。",
                probed=slot,
                details=details,
            )
        if not probe.ready:
            return _result(
                finished,
                day,
                last,
                "源端代码尚未齐备或探测失败，等待下一时点。",
                probed=slot,
                details=details,
            )
        request = C.build_stk_factor_pro_sensor_run_request(
            run_key=build_asset_update_run_key(
                subject=C.STK_FACTOR_PRO_UPDATE_JOB_NAME, unit_id=unit
            ),
            execution_day=day,
            target_trade_date=day,
            scheduled_slot=slot,
        )
        return _result(
            finished,
            day,
            last,
            "源端代码齐备，提交当前交易日日更。",
            probed=slot,
            request=request,
            details=details,
        )


@dg.sensor(
    name=C.STK_FACTOR_PRO_UPDATE_SENSOR_NAME,
    job=raw_tushare_stk_factor_pro_update_job,
    minimum_interval_seconds=C.STK_FACTOR_PRO_UPDATE_SENSOR_INTERVAL_SECONDS,
    default_status=dg.DefaultSensorStatus.STOPPED,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.QUOTE_DATA,
        target_layer=SensorTargetLayer.RAW_SILVER,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="仅上海开市日按半小时时点探测当天代码齐备后提交日更，沿用股票复权因子历史追修。",
)
def raw_tushare_stk_factor_pro_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    return evaluate_stk_factor_pro_update(context)
