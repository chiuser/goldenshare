"""Stock technical factor daily orchestration on one connection and one run."""

from contextlib import closing
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import dagster as dg

from orchestrator.defs.asset_guards import stk_factor_pro_readiness as readiness
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_coverage as coverage_io
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_records as records
from orchestrator.defs.bootstrap import stk_factor_pro_history as initialization
from orchestrator.defs.catalog import get_lake_asset_catalog_entry
from orchestrator.defs.checks.stk_factor_pro import (
    factor_file_identity,
    factor_known_file_sha,
)
from orchestrator.defs.io import stk_factor_pro_download as download
from orchestrator.defs.io import stk_factor_pro_history as history
from orchestrator.defs.io import stk_factor_pro_publication as publication
from orchestrator.defs.io.stk_factor_pro_candidates import (
    RAW_EXPECTED,
    release_stk_factor_pro_day_source,
    require_stk_factor_pro_safe_path,
)
from orchestrator.defs.partitions import cn_a_stock_factor_pro_trade_days
from orchestrator.defs.paths import (
    DEFAULT_LAKE_STAGING_ROOT,
    raw_adj_factor_path,
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
    silver_stock_identity_map_path,
    silver_stock_lifecycle_path,
    silver_stock_suspend_daily_path,
    stk_factor_pro_run_staging_root,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts import stk_factor_pro as C
from orchestrator.defs.run_contracts.asset_tags import build_asset_tags
from orchestrator.defs.run_contracts.metadata import build_asset_definition_metadata
from orchestrator.defs.sensors.readiness import (
    raw_tushare_adj_factor_ready_for_trade_date,
    suspend_d_ready_for_trade_date,
)
from orchestrator.tushare_download import DownloadError, DownloadErrorCode

_RAW = dg.AssetKey(C.STK_FACTOR_PRO_RAW_ASSET_KEY)
_SILVER = dg.AssetKey(C.STK_FACTOR_PRO_SILVER_ASSET_KEY)
_ASSETS = frozenset((_RAW, _SILVER))
_CHECKS = frozenset(
    (
        dg.AssetCheckKey(_RAW, C.STK_FACTOR_PRO_RAW_CHECK_NAME),
        dg.AssetCheckKey(_SILVER, C.STK_FACTOR_PRO_SILVER_CHECK_NAME),
    )
)
_CONTRACT = C.ContractIdentity(
    "stk_factor_pro",
    "1",
    C.STK_FACTOR_PRO_CONTRACT_CONTENT_DIGEST,
    C.STK_FACTOR_PRO_PROCESSING_VERSION,
)


def _asset_spec(key, dependencies):
    entry = get_lake_asset_catalog_entry(key.to_user_string())
    return dg.AssetSpec(
        key,
        deps=dependencies,
        group_name=entry.group_name,
        partitions_def=cn_a_stock_factor_pro_trade_days,
        skippable=True,
        tags=build_asset_tags(layer=entry.layer, data_domain=entry.data_domain),
        metadata=build_asset_definition_metadata(
            dataset_id=entry.dataset_id,
            source_system=entry.source_system,
            data_contract=entry.data_contract,
            column_schema=entry.column_schema,
            path_template=entry.path_template,
            source_api=entry.source_api,
            source_doc=entry.source_doc,
        ),
    )


def _now():
    return datetime.now(ZoneInfo(C.STK_FACTOR_PRO_TIMEZONE))


def _failure(phase, day, summary, *, retryable=False, source_error_code=None):
    return dg.Failure(
        summary,
        allow_retries=False,
        metadata={
            "goldenshare/failure_phase": phase,
            "goldenshare/target_trade_date": str(day),
            "goldenshare/retryable": retryable,
            "goldenshare/source_error_code": source_error_code,
            "goldenshare/summary": summary,
            "goldenshare/next_action": (
                "按原任务范围重新执行。"
                if retryable
                else "请管理员核对原因及本轮已发布文件。"
            ),
        },
    )


def _open_calendar(connection, lake, inherited_facts, known_records):
    path = readiness._GLOBALS["calendar"][0](lake)
    fact = readiness._load_basis(
        connection,
        path=path,
        kind="calendar",
        trade_date=None,
        basis_inputs={"files": inherited_facts},
        known_records=known_records,
    )
    if not fact["basis"].valid:
        raise ValueError(f"股票技术因子缺可用交易日历：{fact['reason']}")
    return dict(
        connection.execute(
            f"SELECT trade_date, pretrade_date FROM {fact['relation']} "
            "WHERE exchange='SSE' AND is_open ORDER BY trade_date"
        ).fetchall()
    )


def _factor_file_refs(connection, lake, dates, known_records):
    paths = tuple(raw_adj_factor_path(lake, str(day)) for day in dates)
    digests = []
    for path in paths:
        require_stk_factor_pro_safe_path(path)
        digest = factor_known_file_sha(path, known_records=known_records)
        if digest is None:
            raise ValueError(f"权威复权因子文件不存在：{path}")
        digests.append(digest)
    sizes = dict(
        connection.execute(
            "SELECT file_name,num_rows FROM parquet_file_metadata(?)",
            [[str(p) for p in paths]],
        ).fetchall()
    )
    return tuple(
        C.FactorFileRef(day, "raw_tushare_adj_factor", digest, sizes[str(path)])
        for day, path, digest in zip(dates, paths, digests, strict=True)
    )


def _history_raw_dates(instance, *, day, calendar, known_pg, initialization_state):
    """Resolve the approved complete date set only when a stock lacks a start."""
    if initialization_state is not None:
        selected = []
        for current, rows in initialization_state["approved_counts"].items():
            if current > day:
                continue
            entry = initialization_state["date_results"][current]
            result = entry["persisted_result"]
            if rows or (result is not None and result.raw_rows):
                if (
                    not entry["current_files_verified"]
                    or result is None
                    or not result.raw_file_sha256
                ):
                    return ()
                selected.append(current)
            elif (
                not entry["current_files_verified"]
                and current
                not in initialization_state["totals"]["sets"]["known_closed_dates"]
            ):
                return ()
        return tuple(sorted(selected))
    key = ("materialized_partitions", C.STK_FACTOR_PRO_RAW_ASSET_KEY)
    if key not in known_pg:
        known_pg[key] = instance.get_materialized_partitions(_RAW)
    dates = tuple(
        sorted(
            observed
            for partition in known_pg[key]
            if (
                observed := date.fromisoformat(
                    C.normalize_stk_factor_pro_trade_date(partition)
                )
            )
            <= day
        )
    )
    return dates if set(dates).issubset(calendar) else ()


def _plan_history(
    connection,
    instance,
    *,
    identity,
    lake,
    staging,
    calendar,
    prior,
    known_pg,
    known_records,
    check_cancel,
    initialization_state,
    prior_history=None,
):
    dates = identity.target_trade_date, identity.previous_trade_date
    factor_t, factor_p = _factor_file_refs(connection, lake, dates, known_records)
    prior_factor_shas = None
    if identity.purpose == "today" and identity.source_run_id is None:
        prior_factor_shas = readiness.read_stk_factor_pro_day_factor_shas(
            instance,
            prior=prior,
            previous_trade_date=identity.previous_trade_date,
            lake_root=lake,
            staging_root=staging,
            contract=_CONTRACT,
            known_pg=known_pg,
            known_records=known_records,
        )
    relations, lifecycle = history.prepare_stk_factor_pro_history_inputs(
        connection,
        identity=identity,
        lake_root=lake,
        factor_t=factor_t,
        factor_p=factor_p,
        known_records=known_records,
        check_cancel=check_cancel,
    )
    comparison = history.compare_stk_factor_pro_history_factors(
        connection,
        factor_relations=relations,
    )
    if prior_history is None:
        prior_history = history.read_stk_factor_pro_prior_history(
            connection,
            staging_root=staging,
            target=identity.target_trade_date,
            contract=_CONTRACT,
            prior=prior,
            known_records=known_records,
        )
    missing = (
        ()
        if identity.purpose == "manual_repair"
        else history.stk_factor_pro_codes_without_history_starts(
            factor_comparison=comparison,
            prior_results=prior,
            prior_history=prior_history,
        )
    )
    starts = ()
    if missing:
        dates = _history_raw_dates(
            instance,
            day=identity.target_trade_date,
            calendar=calendar,
            known_pg=known_pg,
            initialization_state=initialization_state,
        )
        starts = history.resolve_stk_factor_pro_history_starts(
            connection,
            lake_root=lake,
            target_trade_date=identity.target_trade_date,
            codes=missing,
            known_starts=(),
            approved_raw_dates=dates,
            known_records=known_records,
            check_cancel=check_cancel,
        )
    return history.build_stk_factor_pro_history_plan(
        connection,
        identity=identity,
        contract=_CONTRACT,
        lake_root=lake,
        staging_root=staging,
        factor_t=factor_t,
        factor_p=factor_p,
        factor_relations=relations,
        factor_comparison=comparison,
        lifecycle_relation=lifecycle,
        prior_results=prior,
        prior_history=prior_history,
        history_starts=starts,
        check_cancel=check_cancel,
        known_records=known_records,
        factor_revised=prior_factor_shas is not None
        and prior_factor_shas != (factor_t.file_sha256, factor_p.file_sha256),
    )


def _observation(identity, prior, kind, **facts):
    return dg.AssetObservation(
        _RAW,
        partition=str(identity.target_trade_date),
        metadata=C.build_stk_factor_pro_observation_metadata(
            identity=identity,
            recorded_results=prior,
            observation_kind=kind,
            **facts,
        ),
    )


def _saved_observation(instance, identity, kind, known_pg):
    rows = instance.get_records_for_run(
        identity.creator_run_id,
        of_type=dg.DagsterEventType.ASSET_OBSERVATION,
        limit=1,
        ascending=False,
    ).records
    if not rows:
        raise ValueError(f"股票技术因子{kind}观察未持久化")
    record = rows[0]
    result = readiness._stk_factor_pro_observation(
        instance,
        record,
        target=identity.target_trade_date,
        known_pg=known_pg,
    )
    if (
        result["observation_kind"] != kind
        or result["producer_run_id"] != identity.creator_run_id
    ):
        raise ValueError(f"股票技术因子{kind}观察身份不符")
    return C.StkFactorProResultRef(identity.creator_run_id, record.storage_id), result


def _recovered_failure(instance, run, failed_id, bootstrap_context, known_pg):
    if failed_id is None:
        return None
    if run.parent_run_id is not None:
        return failed_id if failed_id in (run.parent_run_id, run.root_run_id) else None
    if bootstrap_context is None:
        previous = readiness.read_stk_factor_pro_failure(
            instance, failed_id, known_pg=known_pg
        )
        return failed_id if previous["retryable"] else None
    failed = readiness.read_stk_factor_pro_run(instance, failed_id, known_pg=known_pg)
    if failed.job_name != C.STK_FACTOR_PRO_UPDATE_JOB_NAME:
        return None
    source = readiness._stk_factor_pro_update_input(failed)
    if (
        source.purpose == "bootstrap_supplement"
        and source.target_trade_date == bootstrap_context.target_trade_date
        and source.bootstrap_operation_id == bootstrap_context.operation_id
        and source.expected_bootstrap_approval_digest
        == bootstrap_context.approval_digest
    ):
        return failed_id
    return None


def _suspend_ready(instance, day, known_pg):
    key = ("suspend_readiness", day)
    if key not in known_pg:
        known_pg[key] = suspend_d_ready_for_trade_date(instance, str(day))
    return known_pg[key].ready


def _basis_for_day(connection, instance, lake, day, inherited, known_pg, known_records):
    inputs = readiness.prepare_stk_factor_pro_coverage_inputs(
        connection,
        lake_root=lake,
        trade_date=day,
        inherited_facts=inherited,
        known_records=known_records,
    )
    if "suspend" in inputs["unknown_input_kinds"]:
        return inputs
    if _suspend_ready(instance, day, known_pg):
        return inputs
    return {
        **inputs,
        "unknown_input_kinds": tuple(
            sorted((*inputs["unknown_input_kinds"], "suspend"))
        ),
        "reason": "; ".join(filter(None, (inputs["reason"], "原日期停牌检查未通过"))),
    }


def _space_for_initialization(identity, stage, *, path, **facts):
    history.require_stk_factor_pro_history_space(
        required_by_path=((path, C.STK_FACTOR_PRO_ESTIMATED_RECORD_BYTES),),
        run_id=identity.creator_run_id,
        stage=stage,
    )


def _prepare_initialization_result(
    connection,
    *,
    lake,
    staging,
    identity,
    state,
    inputs,
    audits,
    known_records,
    check_space,
):
    day = inputs["trade_date"]
    entry = initialization.prepare_stk_factor_pro_bootstrap_supplement_entry(
        connection,
        staging_root=staging,
        approval=state["approval"],
        approval_digest=state["approval_digest"],
        trade_date=day,
        approved_counts=state["approved_counts"],
        date_results=state["date_results"],
        known_records=known_records,
    )
    raw, silver = audits
    if raw is None and silver is None:
        prepared = {
            **inputs,
            "raw_audit": None,
            "silver_audit": None,
            "raw_rows": 0,
            "silver_rows": 0,
            "raw_physical_code_count": 0,
            "raw_file_sha256": None,
            "silver_file_sha256": None,
        }
    else:
        prepared = coverage_io.prepare_stk_factor_pro_bootstrap_supplement_date(
            trade_date=day,
            raw_audit=raw,
            silver_audit=silver,
            coverage_inputs=inputs,
        )
    original = entry["source_complete"]
    digest = coverage_io._date_digest(
        state["approval"],
        state["approval_digest"],
        day,
        original,
        (prepared["raw_file_sha256"], prepared["silver_file_sha256"]),
        prepared["basis_files"],
        prepared["is_open"],
    )
    previous = entry["persisted_result"]
    if (
        previous is not None
        and entry["coverage_record_current"]
        and previous.input_digest == digest
        and (
            day != identity.target_trade_date
            or previous.missing_codes_ref is None
            or previous.missing_codes_ref.creator_run_id is not None
        )
    ):
        calculated = initialization._bootstrap_previous_calculation(previous)
    else:
        calculated = coverage_io.compute_stk_factor_pro_bootstrap_coverage_date(
            connection,
            lake_root=lake,
            staging_root=staging,
            approval=state["approval"],
            prepared=prepared,
            raw_relation=RAW_EXPECTED if raw is not None else None,
            diagnostic_run=identity,
            input_digest=digest,
            check_space=check_space,
            known_records=known_records,
        )
    return prepared, calculated, digest


def _persist_initialization_results(
    connection,
    instance,
    *,
    lake,
    staging,
    identity,
    context,
    state,
    pending,
    audits,
    attempted,
    known_pg,
    known_records,
    check_space,
):
    dates = set(attempted) | {audit.trade_date for audit in audits}
    batch = initialization.read_stk_factor_pro_bootstrap_current_publications(
        instance,
        context=context,
        run_id=identity.creator_run_id,
        audits=audits,
        expected_file_dates=dates,
        attempted_dates=dates,
        known_pg=known_pg,
        known_records=known_records,
    )
    publications = {item.trade_date: item for item in batch.publications}
    entries = state["date_results"]
    totals = state["totals"]
    refs = []
    for day in batch.incomplete_dates:
        entry = initialization.prepare_stk_factor_pro_bootstrap_supplement_entry(
            connection,
            staging_root=staging,
            approval=state["approval"],
            approval_digest=state["approval_digest"],
            trade_date=day,
            approved_counts=state["approved_counts"],
            date_results=entries,
            known_records=known_records,
        )
        entry.update(
            current_files_verified=False,
            coverage_record_current=False,
            unknown_reason="本轮两层发布未完成",
        )
        previous = entry["persisted_result"]
        coverage_io.refresh_stk_factor_pro_bootstrap_date_contribution(
            trade_date=day,
            entry=entry,
            totals=totals,
            is_open=previous.is_open if previous is not None else None,
            approved_rows=state["approved_counts"][day],
        )
    for day, (prepared, calculated, digest) in pending.items():
        entry = entries[day]
        current = publications.get(day)
        if current is None and prepared["raw_audit"] is not None:
            raise ValueError("初始化统计缺本次两层发布事实")
        previous, previous_digest = (
            entry["persisted_result"],
            entry["persisted_result_digest"],
        )
        result = coverage_io.evaluate_stk_factor_pro_bootstrap_coverage_date(
            prepared=prepared,
            calculated=calculated,
            approval_digest=state["approval_digest"],
            input_digest=digest,
            source_complete=entry["source_complete"],
            current_publication=current,
            previous_result=previous,
        )
        entry.update(
            raw_audit=prepared["raw_audit"],
            silver_audit=prepared["silver_audit"],
            current_publication=current,
            current_files_verified=True,
            computed_result=result,
        )
        _, saved_digest = coverage_io.update_stk_factor_pro_bootstrap_after_publication(
            connection,
            lake_root=lake,
            staging_root=staging,
            approval=state["approval"],
            result=result,
            previous_result=previous,
            previous_result_digest=previous_digest,
            known_records=known_records,
            date_results=entries,
            check_space=check_space,
        )
        coverage_io.refresh_stk_factor_pro_bootstrap_date_contribution(
            trade_date=day,
            entry=entry,
            totals=totals,
            is_open=prepared["is_open"],
            approved_rows=state["approved_counts"][day],
        )
        refs.append((day, f"coverage/{day}/result.json", saved_digest))
    summary, sha = coverage_io.summarize_stk_factor_pro_bootstrap_coverage(
        staging_root=staging,
        approval=state["approval"],
        approval_digest=state["approval_digest"],
        totals=totals,
        previous_summary=state["previous_summary"],
        previous_summary_digest=state["previous_summary_digest"],
        check_space=check_space,
        known_records=known_records,
    )
    state.update(previous_summary=summary, previous_summary_digest=sha)
    return {
        "bootstrap_coverage_refs": tuple(sorted(refs)),
        "bootstrap_summary_ref": {
            "relative_path": "coverage/summary.json",
            "file_sha256": sha,
        },
    }


def _progress(context):
    def report(info):
        context.log.info(
            f"股票技术因子 {info.event.name} 单元 {info.completed_units}/{info.total_units}，"
            f"行数 {info.completed_row_count}，请求 {info.request_count}，重试 {info.retry_count}"
        )

    return report


def _log_factor_differences(connection, context, *, source_relation, day):
    count = connection.execute(
        f"SELECT count(*) FROM {source_relation} src "
        "JOIN stk_factor_pro_history_factor_t factor USING (ts_code) "
        "WHERE src.trade_date=? AND src.adj_factor IS DISTINCT FROM factor.adj_factor",
        [day.strftime("%Y%m%d")],
    ).fetchone()[0]
    if count:
        context.log.info(
            f"{day} 技术因子与复权因子数据集的复权因子值不同，共{count}条。"
        )


def _published_day(
    connection,
    context,
    *,
    lake,
    staging,
    identity,
    known_pg,
    known_records,
    inherited,
    bootstrap_context,
    initialization_state,
    control,
    check_cancel,
):
    day = identity.target_trade_date
    source = download.download_stk_factor_pro_day(
        connection,
        identity=identity,
        contract=_CONTRACT,
        control=control,
        check_cancel=check_cancel,
        on_progress=_progress(context),
    )
    source_digest = source.day_source_digest
    completed, attempted = [], set()
    phase_stats = {}

    def attempt(current_day, layer):
        attempted.add(current_day)

    def check_space(stage, **facts):
        return _space_for_initialization(identity, stage, **facts)

    with records.resource_cleanup(
        lambda: release_stk_factor_pro_day_source(connection)
    ):
        try:
            with closing(
                publication.publish_stk_factor_pro_day(
                    connection,
                    source=source,
                    lake_root=lake,
                    staging_root=staging,
                    check_cancel=check_cancel,
                    known_records=known_records,
                    on_publish_attempt=attempt,
                )
            ) as output:
                for target, audit in output:
                    completed.append((target, audit))
                    yield from readiness.emit_stk_factor_pro_publications(
                        context,
                        completed=((target, audit),),
                        lake_root=lake,
                        known_pg=known_pg,
                        known_records=known_records,
                        day_output=True,
                        source_metadata={
                            "goldenshare/day_source_digest": source_digest,
                            "goldenshare/scope_digest": source.scope_digest,
                            "goldenshare/source_manifest_digest": None,
                        },
                    )
        except Exception as primary:
            if initialization_state is not None and attempted:
                try:
                    _persist_initialization_results(
                        connection,
                        context.instance,
                        lake=lake,
                        staging=staging,
                        identity=identity,
                        context=bootstrap_context,
                        state=initialization_state,
                        pending={},
                        audits=tuple(a for _, a in completed),
                        attempted=attempted,
                        known_pg=known_pg,
                        known_records=known_records,
                        check_space=check_space,
                    )
                except Exception as cleanup:  # noqa: BLE001 - retain the publication failure.
                    primary.add_note(f"初始化统计收尾同时失败：{cleanup}")
            raise
        inputs = _basis_for_day(
            connection, context.instance, lake, day, inherited, known_pg, known_records
        )
        raw, silver = (completed[0][1], completed[1][1]) if completed else (None, None)
        if raw is not None:
            _log_factor_differences(
                connection, context, source_relation=RAW_EXPECTED, day=day
            )
        pending = {}
        if initialization_state is not None:
            pending[day] = _prepare_initialization_result(
                connection,
                lake=lake,
                staging=staging,
                identity=identity,
                state=initialization_state,
                inputs=inputs,
                audits=(raw, silver),
                known_records=known_records,
                check_space=check_space,
            )
            calculated = pending[day][1]
        else:
            previous = known_pg[("recorded_results", day)].raw_coverage
            basis = tuple(
                known_records.get(path, (None, None, None))[1]
                for path in (
                    silver_stock_lifecycle_path(lake),
                    silver_stock_suspend_daily_path(lake, str(day)),
                    silver_stock_identity_map_path(lake),
                )
            )
            reusable = (
                raw is not None
                and previous is not None
                and previous.coverage_rule_version == C.STK_FACTOR_PRO_COVERAGE_RULE_VERSION
                and previous.expected_count is not None
                and not inputs["unknown_input_kinds"]
                and inputs["is_open"] is True
                and (raw.file_sha256, *basis)
                == (
                    previous.raw_file_sha256,
                    previous.lifecycle_file_sha256,
                    previous.suspend_file_sha256,
                    previous.identity_file_sha256,
                )
                and history.stk_factor_pro_missing_codes_reusable(
                    previous,
                    staging_root=staging,
                    known_records=known_records,
                )
            )
            calculated = (
                None
                if reusable
                else readiness.calculate_stk_factor_pro_coverage(
                    connection,
                    coverage_inputs=inputs,
                    raw_relation=RAW_EXPECTED if raw is not None else None,
                )
            )
        raw_coverage = readiness.evaluate_stk_factor_pro_raw_coverage(
            context.instance,
            connection,
            lake_root=lake,
            target_trade_date=day,
            known_pg=known_pg,
            known_records=known_records,
            calculated=calculated,
            verified_raw_audit=raw,
        )
        raw_coverage = history.write_stk_factor_pro_missing_codes(
            connection,
            staging_root=staging,
            identity=identity,
            coverage=raw_coverage,
            calculated=calculated,
            known_records=known_records,
        )
        target_silver = (
            None
            if silver is None or raw_coverage.complete is not True
            else readiness.evaluate_stk_factor_pro_target_silver(
                context.instance,
                lake_root=lake,
                raw_coverage=raw_coverage,
                known_pg=known_pg,
                known_records=known_records,
                verified_silver_audit=silver,
            )
        )
        if pending:
            phase_stats = _persist_initialization_results(
                connection,
                context.instance,
                lake=lake,
                staging=staging,
                identity=identity,
                context=bootstrap_context,
                state=initialization_state,
                pending=pending,
                audits=tuple(a for _, a in completed),
                attempted=attempted,
                known_pg=known_pg,
                known_records=known_records,
                check_space=check_space,
            )
        readiness.release_stk_factor_pro_coverage_inputs(
            connection, inherited_facts=inherited, trade_date=day
        )
    return raw_coverage, target_silver, source_digest, phase_stats, bool(completed)


def _publish_history(
    connection,
    context,
    *,
    plan,
    plan_ref,
    ranges,
    units,
    prior,
    recorded_results,
    calendar,
    raw_coverage,
    target_silver,
    lake,
    staging,
    inherited,
    known_pg,
    known_records,
    bootstrap_context,
    initialization_state,
):
    identity = plan.identity
    day = identity.target_trade_date
    control, check_cancel = download.build_stk_factor_pro_run_control(
        context.instance,
        identity=identity,
        phase="history",
    )
    registered = tuple(
        sorted(
            date.fromisoformat(key)
            for key in context.instance.get_dynamic_partitions(
                C.STK_FACTOR_PRO_PARTITIONS
            )
        )
    )
    dates = history.plan_stk_factor_pro_history_publication_dates(
        identity=identity,
        expected_units=units,
        calendar=calendar,
        registered_dates=registered,
    )
    operation_dates = (
        ()
        if initialization_state is None
        else tuple(d for d in dates if d in initialization_state["approved_counts"])
    )
    space = history.build_stk_factor_pro_history_space_check(
        connection,
        identity=identity,
        expected_units=units,
        publication_dates=dates,
        lake_root=lake,
        staging_root=staging,
        known_records=known_records,
        basis_row_counts=tuple(
            fact["basis"].row_count
            for fact in inherited.values()
            if fact["basis"].row_count is not None
        ),
        operation_dates=operation_dates,
    )
    eligibility = C.HistoryEligibilityRecord(
        1,
        identity,
        plan.history_plan_digest,
        plan.history_ranges_digest,
        raw_coverage,
        target_silver,
        _now(),
    )

    original_files = (
        raw_stk_factor_pro_path(lake, str(day)),
        silver_stock_factor_pro_path(lake, str(day)),
        silver_stock_suspend_daily_path(lake, str(day)),
        silver_stock_identity_map_path(lake),
        readiness._GLOBALS["calendar"][0](lake),
    )

    def verified_inputs():
        for path in original_files:
            fact = known_records.get(path)
            if fact is None or factor_file_identity(path) != fact[2]:
                raise ValueError(f"原日期覆盖依据在历史回刷期间改变：{path}")
        return plan.factor_t_ref, plan.factor_p_ref, raw_coverage, target_silver

    planned_revision_codes = {
        row.ts_code
        for row in ranges
        if C.HistoryPlanReason.SAME_NIGHT_FACTOR_REVISION in row.plan_reasons
    }
    revision_codes = tuple(
        unit.object_code for unit in units if unit.object_code in planned_revision_codes
    )
    factor_revision = None
    if revision_codes:
        factor_relations = tuple(
            known_records[raw_adj_factor_path(lake, str(ref.trade_date))][0][0]
            for ref in (plan.factor_t_ref, plan.factor_p_ref)
        )
        factor_revision = factor_relations, revision_codes
    source = download.download_stk_factor_pro_history(
        connection,
        identity=identity,
        contract=plan.contract,
        plan=plan,
        ranges=ranges,
        plan_ref=plan_ref,
        known_records=known_records,
        expected_units=units,
        check_space=space,
        prior_results=prior,
        eligibility=eligibility,
        lake_root=lake,
        staging_root=staging,
        recheck_inputs=verified_inputs,
        control=control,
        check_cancel=check_cancel,
        on_progress=_progress(context),
    )
    completed, pending, attempted = [], {}, set()
    size = C.STK_FACTOR_PRO_HISTORY_MERGE_BATCH_TRADE_DAYS
    batch_ends = set(dates[size - 1 :: size]) | set(dates[-1:])
    operation_days = set(operation_dates)
    last_stats = {}

    def attempt(current_day, layer):
        attempted.add(current_day)

    def flush():
        nonlocal last_stats
        # Detach the batch before yielding so an event-write error cannot replay it.
        files = tuple(completed)
        completed.clear()
        yield from readiness.emit_stk_factor_pro_publications(
            context,
            completed=files,
            lake_root=lake,
            known_pg=known_pg,
            known_records=known_records,
            source_metadata={
                "goldenshare/source_manifest_digest": source.source_complete.files_manifest_digest
            },
        )
        if initialization_state is not None and (pending or attempted):
            last_stats = _persist_initialization_results(
                connection,
                context.instance,
                lake=lake,
                staging=staging,
                identity=identity,
                context=bootstrap_context,
                state=initialization_state,
                pending=pending,
                audits=tuple(a for _, a in files if a is not None),
                attempted=attempted,
                known_pg=known_pg,
                known_records=known_records,
                check_space=space,
            )
        if files:
            published_files = sum(audit is not None for _, audit in files)
            yield _observation(
                identity,
                recorded_results,
                "history",
                result="waiting",
                raw_coverage=raw_coverage,
                target_silver=target_silver,
                bootstrap_context=bootstrap_context,
                **last_stats,
                source_complete_digest=source.source_complete_ref.file_sha256,
                summary=f"已确认本批历史发布 {published_files} 份文件，整段范围尚待确认。",
                next_action="核对本轮所有计划日期的结果。",
            )
        for target, audit in files:
            if audit is not None:
                asset, check = (
                    (C.STK_FACTOR_PRO_RAW_ASSET_KEY, C.STK_FACTOR_PRO_RAW_CHECK_NAME)
                    if target.layer == "raw"
                    else (
                        C.STK_FACTOR_PRO_SILVER_ASSET_KEY,
                        C.STK_FACTOR_PRO_SILVER_CHECK_NAME,
                    )
                )
                known_pg.pop(
                    (
                        "publication_events",
                        identity.creator_run_id,
                        target.trade_date,
                        target.layer,
                    ),
                    None,
                )
                known_pg.pop(("materialization", asset, target.trade_date), None)
                known_pg.pop(("check_execution", asset, check, target.trade_date), None)
        attempted.clear()
        pending.clear()

    with closing(
        publication.publish_stk_factor_pro_history(
            connection,
            source=source,
            known_records=known_records,
            plan=plan,
            ranges=ranges,
            lake_root=lake,
            staging_root=staging,
            calendar=calendar,
            registered_dates=registered,
            publication_dates=dates,
            check_space=space,
            recheck_inputs=verified_inputs,
            check_cancel=check_cancel,
            on_publish_attempt=attempt,
            factor_revision=factor_revision,
        )
    ) as output:
        if factor_revision is None:
            _log_factor_differences(
                connection, context, source_relation=source.source_relation, day=day
            )
        while True:
            try:
                item = next(output, None)
                if item is not None:
                    target, audit = item
                    completed.append(item)
                    current = target.trade_date
                    if (
                        target.layer == "silver"
                        and audit is not None
                        and current in operation_days
                    ):
                        raw = completed[-2][1]
                        inputs = _basis_for_day(
                            connection,
                            context.instance,
                            lake,
                            current,
                            inherited,
                            known_pg,
                            known_records,
                        )
                        pending[current] = _prepare_initialization_result(
                            connection,
                            lake=lake,
                            staging=staging,
                            identity=identity,
                            state=initialization_state,
                            inputs=inputs,
                            audits=(raw, audit),
                            known_records=known_records,
                            check_space=space,
                        )
                        readiness.release_stk_factor_pro_coverage_inputs(
                            connection,
                            inherited_facts=inherited,
                            trade_date=current,
                        )
            except Exception as primary:
                if completed or attempted:
                    try:
                        yield from flush()
                    except Exception as secondary:  # noqa: BLE001 - preserve the failed history stage.
                        primary.add_note(f"历史发布收尾同时失败：{secondary}")
                raise
            if item is None:
                break
            if target.layer == "silver" and target.trade_date in batch_ends:
                yield from flush()
    root = stk_factor_pro_run_staging_root(staging, identity.creator_run_id, str(day))
    return (
        source.source_complete_ref.file_sha256,
        known_records[root / "publication/history/publication-complete.json"][1],
        last_stats,
    )


@dg.multi_asset(
    name="stk_factor_pro",
    specs=[
        _asset_spec(
            _RAW,
            [
                "raw_tushare_adj_factor",
                "silver_trade_calendar",
                "silver_stock_lifecycle",
                "silver_stock_identity_map",
                "silver_stock_suspend_daily",
            ],
        ),
        _asset_spec(_SILVER, [_RAW]),
    ],
    check_specs=[
        dg.AssetCheckSpec(
            key.name,
            asset=key.asset_key,
            blocking=True,
            partitions_def=cn_a_stock_factor_pro_trade_days,
        )
        for key in sorted(_CHECKS, key=lambda check: check.name)
    ],
    can_subset=True,
    config_schema=C.STK_FACTOR_PRO_UPDATE_CONFIG_SCHEMA,
)
def stk_factor_pro(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
):
    day = context.partition_key if context.has_partition_key else ""
    if (
        context.selected_asset_keys != _ASSETS
        or context.selected_asset_check_keys != _CHECKS
    ):
        raise _failure(
            "precheck", day, "股票技术因子必须同时选择Raw、Silver和两项检查。"
        )
    phase = "precheck"
    known_records, known_pg, inherited = {}, {}, {}
    instance = context.instance
    run = context.run
    try:
        blocked = ""
        try:
            active = readiness.read_stk_factor_pro_other_active_runs(
                instance,
                own_run_id=run.run_id,
                active_statuses=C.STK_FACTOR_PRO_RUNNING_RUN_STATUSES,
            )
            if active:
                blocked = "已有其他股票技术因子写入任务正在运行"
        except Exception as error:  # noqa: BLE001 - unreadable activity is a precheck wait, never a free slot.
            blocked = f"无法确认股票技术因子唯一写入：{type(error).__name__}"
        lake_root.ensure_available_for_run()
        lake, staging = lake_root.root(), Path(DEFAULT_LAKE_STAGING_ROOT)
        with (
            duckdb.connect() as connection,
            records.resource_cleanup(
                lambda: history.release_stk_factor_pro_history_inputs(connection),
                lambda: readiness.release_stk_factor_pro_coverage_inputs(
                    connection, inherited_facts=inherited
                ),
            ),
        ):
            calendar_days = _open_calendar(connection, lake, inherited, known_records)
            run_input = C.parse_stk_factor_pro_run_input(
                context.op_execution_context.op_config, day, calendar_days
            )
            calendar = tuple(calendar_days)
            target = run_input.target_trade_date
            if not instance.has_dynamic_partition(
                C.STK_FACTOR_PRO_PARTITIONS, str(target)
            ):
                raise ValueError("股票技术因子目标日尚未登记分区")
            previous = calendar_days[target]
            prior = readiness.read_stk_factor_pro_recorded_results(
                instance,
                target_trade_date=target,
                known_pg=known_pg,
                exclude_run_id=run.run_id,
            )
            init_context = init_state = None
            source_run_id = None
            if run_input.purpose == "bootstrap_supplement":
                init_context = initialization.resolve_stk_factor_pro_bootstrap_context(
                    instance,
                    connection,
                    lake_root=lake,
                    staging_root=staging,
                    current_run=run,
                    run_input=run_input,
                    calendar=calendar,
                    known_pg=known_pg,
                    known_records=known_records,
                )
                init_state = known_pg[
                    ("bootstrap_supplement", init_context.operation_id)
                ]
                source_run_id = run.parent_run_id
            else:
                source_run = readiness.resolve_stk_factor_pro_source_run(
                    instance,
                    run,
                    run_input,
                    known_pg=known_pg,
                    known_records=known_records,
                )
                if source_run is not None:
                    source_run_id = source_run.parent_run_id
                elif run_input.purpose == "manual_date":
                    if _now().date() != run_input.execution_day:
                        raise ValueError("首次指定日期补数的D必须是本次上海日期")
                elif not blocked:
                    now = _now()
                    starts_at = datetime.combine(
                        run_input.execution_day,
                        time(C.STK_FACTOR_PRO_FIRST_SLOT_HOUR),
                        now.tzinfo,
                    ) + timedelta(
                        minutes=run_input.scheduled_slot * C.STK_FACTOR_PRO_SLOT_MINUTES
                    )
                    if now.date() != run_input.execution_day or now < starts_at:
                        blocked = "自动任务不在原执行日计划时点至午夜的窗口"
            identity = C.RunIdentity(
                run.run_id,
                source_run_id,
                run_input.execution_day,
                target,
                previous,
                run_input.purpose,
                run_input.scheduled_slot,
            )
            if not blocked:
                for factor_day in (target, previous):
                    ready = raw_tushare_adj_factor_ready_for_trade_date(
                        instance, str(factor_day)
                    )
                    if not ready.ready:
                        blocked = f"权威复权因子未就绪：{factor_day}，{ready.reason}"
                        break
            if blocked:
                yield _observation(
                    identity,
                    prior,
                    "precheck",
                    bootstrap_context=init_context,
                    summary=f"PRECHECK_NO_DOWNLOAD：{blocked}",
                    next_action="核对上游或任务时点，保留原执行规则。",
                )
                return
            control, check_cancel = download.build_stk_factor_pro_run_control(
                instance, identity=identity, phase="day"
            )
            plan, ranges, plan_ref = _plan_history(
                connection,
                instance,
                identity=identity,
                lake=lake,
                staging=staging,
                calendar=calendar,
                prior=prior,
                known_pg=known_pg,
                known_records=known_records,
                check_cancel=check_cancel,
                initialization_state=init_state,
            )
            current = replace(
                prior,
                history_plan_ref=plan_ref,
                history_ranges_ref=plan.ranges_ref,
                pending_plan_refs=(plan_ref,) if ranges else (),
            )
            yield _observation(
                identity,
                current,
                "start",
                bootstrap_context=init_context,
                summary=f"已保存完整范围，开始下载{target}。",
                next_action="读取当日技术因子并核对发布结果。",
            )
            _, started = _saved_observation(instance, identity, "start", known_pg)
            if not started["goldenshare/download_started"] or (
                started["history_plan_ref"],
                started["history_ranges_ref"],
                started["bootstrap_context"],
            ) != (plan_ref, plan.ranges_ref, init_context):
                raise ValueError("开始观察与本次计划或授权不一致")
            phase = "day"
            raw, silver, day_digest, stats, usable = yield from _published_day(
                connection,
                context,
                lake=lake,
                staging=staging,
                identity=identity,
                known_pg=known_pg,
                known_records=known_records,
                inherited=inherited,
                bootstrap_context=init_context,
                initialization_state=init_state,
                control=control,
                check_cancel=check_cancel,
            )
            complete = raw.complete is True and silver is not None and silver.ready
            recovery = (
                _recovered_failure(
                    instance,
                    run,
                    prior.unresolved_day_failure_run_id,
                    init_context,
                    known_pg,
                )
                if usable
                else None
            )
            yield _observation(
                identity,
                current,
                "day",
                result="completed" if usable else "waiting",
                raw_coverage=raw,
                target_silver=silver,
                day_source_digest=day_digest,
                recovery_of_run_id=recovery,
                bootstrap_context=init_context,
                **stats,
                summary=(
                    f"{target} 日文件已发布，应有 {raw.expected_count}，参与核对 {raw.actual_count}，缺失 {raw.missing_count}，额外 {raw.extra_count}。"
                    if usable
                    else f"{target} 请求成功，源返回0行，当前无可用日文件。"
                ),
                next_action="原T两层就绪后处理必要历史。",
            )
            if not usable and raw.expected_count:
                raise _failure(
                    "day",
                    target,
                    f"目标日尚无可用技术因子数据：{target}；应有{raw.expected_count}只，实际0只。",
                    retryable=True,
                )
            day_ref, _ = _saved_observation(instance, identity, "day", known_pg)
            current = replace(
                current,
                day_result_ref=day_ref,
                raw_coverage=raw,
                unresolved_day_failure_run_id=None
                if recovery
                else prior.unresolved_day_failure_run_id,
            )
            phase = "history"
            history_facts = {
                "bootstrap_context": init_context,
                "raw_coverage": raw,
                "target_silver": silver,
            }
            if not complete:
                root = stk_factor_pro_run_staging_root(staging, run.run_id, str(target))
                history._json_write(
                    root,
                    identity,
                    "history-eligibility.json",
                    C.HistoryEligibilityRecord(
                        1,
                        identity,
                        plan.history_plan_digest,
                        plan.history_ranges_digest,
                        raw,
                        silver,
                        _now(),
                    ),
                    known_records=known_records,
                    check_space=None,
                )
                yield _observation(
                    identity,
                    current,
                    "history",
                    result="waiting",
                    **history_facts,
                    summary="原日期Raw齐备或Silver检查条件尚未满足。",
                    next_action="等待原日期两层就绪。",
                )
                if silver is not None:
                    readiness.require_stk_factor_pro_history_silver(silver)
                return
            if (
                source_run_id is None
                and init_context is None
                and prior.unresolved_history_failure_run_id
            ):
                previous_failure = readiness.read_stk_factor_pro_failure(
                    instance,
                    prior.unresolved_history_failure_run_id,
                    known_pg=known_pg,
                )
                if not previous_failure["retryable"]:
                    yield _observation(
                        identity,
                        current,
                        "history",
                        result="waiting",
                        **history_facts,
                        summary="原历史永久失败等待人工处理。",
                        next_action="管理员核对失败后重新执行。",
                    )
                    return
            unknown = tuple(
                row.ts_code
                for row in ranges
                if C.HistoryPlanReason.NO_PRIOR_HISTORY not in row.plan_reasons
                and (not row.t_present or not row.p_present or row.start_date is None)
            )
            if unknown:
                yield _observation(
                    identity,
                    current,
                    "history",
                    result="waiting",
                    **history_facts,
                    summary=f"历史范围尚未判明，共{len(unknown)}只，样本：{', '.join(unknown[:20])}。",
                    next_action="核对缺失复权因子或最早日期。",
                )
                return
            units = history.resolve_stk_factor_pro_history_units(
                connection,
                plan=plan,
                ranges=ranges,
                prior_results=prior,
                staging_root=staging,
                known_records=known_records,
            )
            if not units:
                yield _observation(
                    identity,
                    replace(current, pending_plan_refs=()),
                    "history",
                    result="no_action",
                    **history_facts,
                    summary="本轮没有待回刷历史。",
                    next_action="按现有调度继续。",
                )
                return
            try:
                source_digest, complete_digest, stats = yield from _publish_history(
                    connection,
                    context,
                    plan=plan,
                    plan_ref=plan_ref,
                    ranges=ranges,
                    units=units,
                    prior=prior,
                    recorded_results=current,
                    calendar=calendar,
                    raw_coverage=raw,
                    target_silver=silver,
                    lake=lake,
                    staging=staging,
                    inherited=inherited,
                    known_pg=known_pg,
                    known_records=known_records,
                    bootstrap_context=init_context,
                    initialization_state=init_state,
                )
            except Exception as error:
                root = stk_factor_pro_run_staging_root(staging, run.run_id, str(target))
                source_fact = known_records.get(
                    root / "source/history/source-complete.json"
                )
                yield _observation(
                    identity,
                    current,
                    "history",
                    result="waiting",
                    **history_facts,
                    source_complete_digest=source_fact[1] if source_fact else None,
                    summary=f"历史未完成：{type(error).__name__}。",
                    next_action="按完整原范围处理失败。",
                )
                raise
            yield _observation(
                identity,
                current,
                "history",
                result="completed",
                **history_facts,
                **stats,
                source_complete_digest=source_digest,
                publication_complete_digest=complete_digest,
                recovery_of_run_id=_recovered_failure(
                    instance,
                    run,
                    prior.unresolved_history_failure_run_id,
                    init_context,
                    known_pg,
                ),
                summary="已完成本轮必要历史回刷及两层检查。",
                next_action="按现有调度继续。",
            )
    except DownloadError as error:
        raise _failure(
            phase,
            day,
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
        failure = _failure(phase, day, error.description or "股票技术因子执行失败。")
        raise dg.Failure(
            failure.description,
            metadata={**failure.metadata, **(error.metadata or {})},
            allow_retries=False,
        ) from error
    except (ValueError, OSError) as error:
        raise _failure(phase, day, str(error) or type(error).__name__) from error
    except Exception as error:
        raise _failure(
            phase, day, f"股票技术因子{phase}执行失败：{type(error).__name__}"
        ) from error
