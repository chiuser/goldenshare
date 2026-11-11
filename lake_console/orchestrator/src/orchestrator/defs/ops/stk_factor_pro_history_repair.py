"""Authorized historical stock-factor repair, starting from original DG results."""

from dataclasses import replace
from datetime import date
from pathlib import Path

import dagster as dg

from orchestrator.defs.asset_guards import stk_factor_pro_readiness as readiness
from orchestrator.defs.assets import stk_factor_pro as daily
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_records as records
from orchestrator.defs.bootstrap import stk_factor_pro_history as initialization
from orchestrator.defs.checks.stk_factor_pro import factor_known_file_sha
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io import stk_factor_pro_download as download
from orchestrator.defs.io import stk_factor_pro_history as history
from orchestrator.defs.io.stk_factor_pro_candidates import (
    require_stk_factor_pro_safe_path,
)
from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_identity_map_path,
    silver_stock_lifecycle_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts import stk_factor_pro as C
from orchestrator.tushare_download import DownloadError, DownloadErrorCode

_CONFIG = {
    "target_trade_date": dg.Field(str),
    "source_run_id": dg.Field(str),
    "expected_history_plan_digest": dg.Field(str),
    "expected_history_ranges_digest": dg.Field(str),
}
_TERMINAL = (
    dg.DagsterRunStatus.SUCCESS,
    dg.DagsterRunStatus.FAILURE,
    dg.DagsterRunStatus.CANCELED,
)


def _first_observation(instance, run_id, day, known_pg):
    key = ("first_observation", run_id)
    if key not in known_pg:
        known_pg[key] = tuple(
            instance.get_records_for_run(
                run_id,
                of_type=dg.DagsterEventType.ASSET_OBSERVATION,
                limit=1,
                ascending=True,
            ).records
        )
    observations = known_pg[key]
    if not observations:
        raise ValueError("原任务没有已保存的完整历史授权")
    values = readiness._stk_factor_pro_observation(
        instance,
        observations[0],
        target=day,
        known_pg=known_pg,
    )
    if values["producer_run_id"] != run_id:
        raise ValueError("原任务的历史授权身份不符")
    return values


def _load_original_scope(
    connection,
    instance,
    *,
    day,
    source_id,
    config,
    staging,
    known_pg,
    known_records,
    prior,
):
    source_run = readiness.read_stk_factor_pro_run(
        instance, source_id, known_pg=known_pg
    )
    if (
        source_run.job_name not in C.STK_FACTOR_PRO_WRITE_JOB_NAMES
        or source_run.status not in _TERMINAL
        or readiness._stk_factor_pro_run_target(source_run) != day
    ):
        raise ValueError("历史repair来源必须是同一原日期的已结束日更或历史repair任务")
    values = _first_observation(instance, source_id, day, known_pg)
    plan_ref, ranges_ref = values["history_plan_ref"], values["history_ranges_ref"]
    if (
        plan_ref is None
        or ranges_ref is None
        or plan_ref.creator_run_id != source_id
        or ranges_ref.creator_run_id != source_id
        or values["observation_kind"] not in ("start", "history")
    ):
        raise ValueError("原任务没有已保存的完整历史计划和范围")
    authorized_prior = replace(
        prior, history_plan_ref=plan_ref, history_ranges_ref=ranges_ref
    )
    prior_history = history.read_stk_factor_pro_prior_history(
        connection,
        staging_root=staging,
        target=day,
        contract=daily._CONTRACT,
        prior=authorized_prior,
        known_records=known_records,
    )
    _, load_plan = prior_history
    source_plan, _ = load_plan(plan_ref)
    origin_ref = source_plan.origin_plan_ref or plan_ref
    origin, _ = load_plan(origin_ref)
    digests = origin.history_plan_digest, origin.history_ranges_digest
    if digests != (
        config["expected_history_plan_digest"],
        config["expected_history_ranges_digest"],
    ):
        raise ValueError("历史repair批准的原完整计划或范围摘要不符")
    if source_plan.origin_plan_ref is not None and digests != (
        source_plan.origin_history_plan_digest,
        source_plan.origin_history_ranges_digest,
    ):
        raise ValueError("前次repair未绑定同一原完整范围")
    return (
        authorized_prior,
        prior_history,
        source_plan,
        origin_ref,
        values["bootstrap_context"],
    )


def _initialization_state(
    connection, instance, *, bootstrap_context, staging, day, known_pg, known_records
):
    if bootstrap_context is None:
        return None
    auth_id = bootstrap_context.authorization_run_id
    auth = readiness.read_stk_factor_pro_run(instance, auth_id, known_pg=known_pg)
    if (
        auth.job_name != C.STK_FACTOR_PRO_UPDATE_JOB_NAME
        or auth.status not in _TERMINAL
        or readiness._stk_factor_pro_run_target(auth) != day
    ):
        raise ValueError("历史repair的初始化补数原授权任务无效")
    run_input = readiness._stk_factor_pro_update_input(auth)
    saved = _first_observation(instance, auth_id, day, known_pg)
    if (
        run_input.purpose != "bootstrap_supplement"
        or run_input.bootstrap_operation_id != bootstrap_context.operation_id
        or run_input.expected_bootstrap_approval_digest
        != bootstrap_context.approval_digest
        or run_input.expected_bootstrap_date_result_digest
        != bootstrap_context.authorized_date_result_digest
        or not saved["goldenshare/download_started"]
        or saved["bootstrap_context"] != bootstrap_context
    ):
        raise ValueError("历史repair的初始化补数原开始授权不符")
    return initialization.load_stk_factor_pro_bootstrap_supplement_authorization(
        connection,
        staging_root=staging,
        operation_id=bootstrap_context.operation_id,
        approval_digest=bootstrap_context.approval_digest,
        day=day,
        known_pg=known_pg,
        known_records=known_records,
    )


def _read_original_daily_publication(
    connection,
    instance,
    *,
    day,
    lake,
    staging,
    identity,
    prior,
    inherited,
    known_pg,
    known_records,
):
    path = raw_stk_factor_pro_path(lake, str(day))
    try:
        _, _, sha, _, _ = readiness._stk_factor_pro_file_result(
            instance,
            layer="raw",
            target_trade_date=day,
            lake_root=lake,
            known_pg=known_pg,
            known_records=known_records,
        )
    except (ValueError, OSError) as error:
        return C.StkFactorProRawCoverage(
            day,
            False,
            False,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            C.STK_FACTOR_PRO_COVERAGE_RULE_VERSION,
            (),
            str(error),
            None,
            None,
            None,
        ), None
    previous = prior.raw_coverage
    reusable = False
    if (
        previous is not None
        and previous.coverage_rule_version == C.STK_FACTOR_PRO_COVERAGE_RULE_VERSION
        and previous.raw_check_passed
        and previous.expected_count is not None
        and previous.raw_file_sha256 == sha
        and daily._suspend_ready(instance, day, known_pg)
    ):
        basis = []
        for file in (
            silver_stock_lifecycle_path(lake),
            silver_stock_suspend_daily_path(lake, str(day)),
            silver_stock_identity_map_path(lake),
        ):
            require_stk_factor_pro_safe_path(file)
            try:
                basis.append(factor_known_file_sha(file, known_records=known_records))
            except OSError:
                basis.append(None)
        reusable = tuple(basis) == (
            previous.lifecycle_file_sha256,
            previous.suspend_file_sha256,
            previous.identity_file_sha256,
        ) and history.stk_factor_pro_missing_codes_reusable(
            previous,
            staging_root=staging,
            known_records=known_records,
        )
    calculated = None
    if not reusable:
        inputs = daily._basis_for_day(
            connection,
            instance,
            lake,
            day,
            inherited,
            known_pg,
            known_records,
        )
        raw_keys = "stk_factor_pro_repair_raw_keys"
        if not inputs["unknown_input_kinds"]:
            connection.execute(
                f"CREATE TEMP VIEW {raw_keys} AS SELECT ts_code,trade_date "
                f"FROM {read_parquet(path, hive_partitioning=False)}"
            )
        with records.resource_cleanup(
            lambda: connection.execute(f"DROP VIEW IF EXISTS {raw_keys}")
        ):
            calculated = readiness.calculate_stk_factor_pro_coverage(
                connection,
                coverage_inputs=inputs,
                raw_relation=raw_keys,
            )
    try:
        coverage = readiness.evaluate_stk_factor_pro_raw_coverage(
            instance,
            connection,
            lake_root=lake,
            target_trade_date=day,
            known_pg=known_pg,
            known_records=known_records,
            calculated=calculated,
        )
        coverage = history.write_stk_factor_pro_missing_codes(
            connection,
            staging_root=staging,
            identity=identity,
            coverage=coverage,
            calculated=calculated,
            known_records=known_records,
        )
    finally:
        if calculated is not None:
            readiness.release_stk_factor_pro_coverage_keys(
                connection, coverage_inputs=inputs
            )
    if coverage.complete is not True or not coverage.raw_check_passed:
        return coverage, None
    silver = readiness.evaluate_stk_factor_pro_target_silver(
        instance,
        lake_root=lake,
        raw_coverage=coverage,
        known_pg=known_pg,
        known_records=known_records,
    )
    return coverage, silver


@dg.op(name="repair_stk_factor_pro_history", out={}, config_schema=_CONFIG)
def repair_stk_factor_pro_history(
    context: dg.OpExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
):
    config = context.op_config
    target = config["target_trade_date"]
    try:
        if C.normalize_stk_factor_pro_trade_date(target) != target:
            raise ValueError("历史repair目标必须是ISO交易日期")
        day = date.fromisoformat(target)
        source_id = C.validate_stk_factor_pro_identifier(config["source_run_id"])
        for key in ("expected_history_plan_digest", "expected_history_ranges_digest"):
            C._digest(config[key])
        instance = context.instance
        run_id = context.run.run_id
        if readiness.read_stk_factor_pro_other_active_runs(
            instance,
            own_run_id=run_id,
            active_statuses=C.STK_FACTOR_PRO_RUNNING_RUN_STATUSES,
        ):
            raise ValueError("已有其他股票技术因子写入任务正在运行，请完成后重新执行")
        lake_root.ensure_available_for_run()
        lake, staging = lake_root.root(), Path(daily.DEFAULT_LAKE_STAGING_ROOT)
        known_pg, known_records, inherited = {}, {}, {}
        with (
            duckdb.connect() as connection,
            records.resource_cleanup(
                lambda: history.release_stk_factor_pro_history_inputs(connection),
                lambda: readiness.release_stk_factor_pro_coverage_inputs(
                    connection, inherited_facts=inherited
                ),
            ),
        ):
            prior = readiness.read_stk_factor_pro_recorded_results(
                instance,
                target_trade_date=day,
                known_pg=known_pg,
                exclude_run_id=run_id,
            )
            auth_prior, prior_history, source_plan, origin_ref, bootstrap_context = (
                _load_original_scope(
                    connection,
                    instance,
                    day=day,
                    source_id=source_id,
                    config=config,
                    staging=staging,
                    known_pg=known_pg,
                    known_records=known_records,
                    prior=prior,
                )
            )
            calendar = daily._open_calendar(connection, lake, inherited, known_records)
            if (
                day not in calendar
                or calendar.index(day) == 0
                or not instance.has_dynamic_partition(
                    C.STK_FACTOR_PRO_PARTITIONS, str(day)
                )
            ):
                raise ValueError("历史repair原日期不是已登记且有前交易日的开市日")
            previous = calendar[calendar.index(day) - 1]
            if previous != source_plan.identity.previous_trade_date:
                raise ValueError("历史repair的原前交易日已改变")
            identity = C.RunIdentity(
                run_id,
                source_id,
                daily._now().date(),
                day,
                previous,
                "manual_repair",
                None,
                None,
                None,
            )
            raw, silver = _read_original_daily_publication(
                connection,
                instance,
                day=day,
                lake=lake,
                staging=staging,
                identity=identity,
                prior=prior,
                inherited=inherited,
                known_pg=known_pg,
                known_records=known_records,
            )
            if raw.complete is not True or silver is None or not silver.ready:
                eligibility = C.HistoryEligibilityRecord(
                    1,
                    identity,
                    config["expected_history_plan_digest"],
                    config["expected_history_ranges_digest"],
                    raw,
                    silver,
                    daily._now(),
                )
                root = history.stk_factor_pro_run_staging_root(
                    staging, run_id, str(day)
                )
                history._json_write(
                    root,
                    identity,
                    "history-eligibility.json",
                    eligibility,
                    known_records=known_records,
                    check_space=None,
                )
                yield daily._observation(
                    identity,
                    auth_prior,
                    "history",
                    result="waiting",
                    raw_coverage=raw,
                    target_silver=silver,
                    bootstrap_context=bootstrap_context,
                    summary="原日期未通过历史回刷条件。",
                    next_action="请管理员处理原日期后重新执行历史repair。",
                )
                readiness.require_stk_factor_pro_history_raw(raw)
                readiness.require_stk_factor_pro_history_silver(silver)
            state = _initialization_state(
                connection,
                instance,
                bootstrap_context=bootstrap_context,
                staging=staging,
                day=day,
                known_pg=known_pg,
                known_records=known_records,
            )
            _, check_cancel = download.build_stk_factor_pro_run_control(
                instance, identity=identity, phase="history"
            )
            for factor_day in (day, previous):
                ready = daily.raw_tushare_adj_factor_ready_for_trade_date(
                    instance, str(factor_day)
                )
                if not ready.ready:
                    raise ValueError(
                        f"原日期权威复权因子未就绪：{factor_day}，{ready.reason}"
                    )
            plan, ranges, plan_ref = daily._plan_history(
                connection,
                instance,
                identity=identity,
                lake=lake,
                staging=staging,
                calendar=calendar,
                prior=auth_prior,
                known_pg=known_pg,
                known_records=known_records,
                check_cancel=check_cancel,
                initialization_state=state,
                prior_history=prior_history,
            )
            # The authorized scope can replace only its own old intent.
            pending = tuple(
                ref
                for ref in prior.pending_plan_refs
                if ref not in (origin_ref, auth_prior.history_plan_ref)
            )
            current = replace(
                prior,
                history_plan_ref=plan_ref,
                history_ranges_ref=plan.ranges_ref,
                pending_plan_refs=(*pending, plan_ref) if ranges else pending,
                raw_coverage=raw,
            )
            facts = {
                "raw_coverage": raw,
                "target_silver": silver,
                "bootstrap_context": bootstrap_context,
            }
            try:
                units = history.resolve_stk_factor_pro_history_units(
                    connection,
                    plan=plan,
                    ranges=ranges,
                    prior_results=auth_prior,
                    staging_root=staging,
                    known_records=known_records,
                )
                if not units:
                    yield daily._observation(
                        identity,
                        replace(current, pending_plan_refs=pending),
                        "history",
                        result="no_action",
                        **facts,
                        summary="原授权范围没有待回刷的历史。",
                        next_action="保留原已确认成功的结果。",
                    )
                    return
                yield daily._observation(
                    identity,
                    current,
                    "start",
                    **facts,
                    summary="原日期两层有效，准备重新下载原授权历史。",
                    next_action="按原完整范围回刷早于原日期的数据。",
                )
                _, started = daily._saved_observation(
                    instance, identity, "start", known_pg
                )
                if (
                    started["history_plan_ref"],
                    started["history_ranges_ref"],
                    started["bootstrap_context"],
                ) != (plan_ref, plan.ranges_ref, bootstrap_context):
                    raise ValueError("历史repair开始观察与本次完整授权不一致")
                (
                    source_digest,
                    complete_digest,
                    stats,
                ) = yield from daily._publish_history(
                    connection,
                    context,
                    plan=plan,
                    plan_ref=plan_ref,
                    ranges=ranges,
                    units=units,
                    prior=auth_prior,
                    recorded_results=current,
                    calendar=calendar,
                    raw_coverage=raw,
                    target_silver=silver,
                    lake=lake,
                    staging=staging,
                    inherited=inherited,
                    known_pg=known_pg,
                    known_records=known_records,
                    bootstrap_context=bootstrap_context,
                    initialization_state=state,
                )
            except Exception as error:
                root = history.stk_factor_pro_run_staging_root(
                    staging, run_id, str(day)
                )
                source_fact = known_records.get(
                    root / "source/history/source-complete.json"
                )
                yield daily._observation(
                    identity,
                    current,
                    "history",
                    result="waiting",
                    **facts,
                    source_complete_digest=source_fact[1] if source_fact else None,
                    summary=f"原授权历史尚未完成：{type(error).__name__}。",
                    next_action="请管理员处理原因后重新执行历史repair。",
                )
                raise
            yield daily._observation(
                identity,
                current,
                "history",
                result="completed",
                **facts,
                **stats,
                source_complete_digest=source_digest,
                publication_complete_digest=complete_digest,
                recovery_of_run_id=source_id,
                summary="原授权历史已完整发布并通过两层检查。",
                next_action="可在DG查看本次原范围结果。",
            )
    except DownloadError as error:
        raise daily._failure(
            "history",
            target,
            str(error),
            retryable=error.code
            in (
                DownloadErrorCode.RATE_LIMIT,
                DownloadErrorCode.TRANSIENT_SOURCE,
                DownloadErrorCode.NO_VALID_RESPONSE,
            ),
            source_error_code=int(error.code),
        ) from error
    except dg.Failure as error:
        if "goldenshare/target_trade_date" in (error.metadata or {}):
            raise
        raise daily._failure(
            "history", target, error.description or "历史repair执行失败。"
        ) from error
    except (ValueError, OSError) as error:
        raise daily._failure("history", target, str(error)) from error
    except Exception as error:
        raise daily._failure(
            "history", target, f"历史repair执行失败：{type(error).__name__}"
        ) from error
