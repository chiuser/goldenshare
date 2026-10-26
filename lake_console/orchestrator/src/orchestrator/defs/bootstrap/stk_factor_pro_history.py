"""Single approved Prod bootstrap entry; daily jobs and event readers live elsewhere."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from orchestrator.defs.asset_guards.stk_factor_pro_readiness import (
    require_stk_factor_pro_no_other_active_runs,
)
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_records as R
from orchestrator.defs.bootstrap import stk_factor_pro_bootstrap_source as S
from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_coverage import (
    evaluate_stk_factor_pro_bootstrap_coverage_date,
    prepare_stk_factor_pro_bootstrap_coverage_month,
    release_stk_factor_pro_bootstrap_coverage_month,
    summarize_stk_factor_pro_bootstrap_coverage,
    update_stk_factor_pro_bootstrap_after_publication,
    write_stk_factor_pro_bootstrap_coverage_date,
)
from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_publication import (
    publish_bootstrap_date,
    read_stk_factor_pro_bootstrap_publication,
    write_stk_factor_pro_bootstrap_publication_complete,
    write_stk_factor_pro_bootstrap_publication_intent,
)
from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_records import (
    read_stk_factor_pro_bootstrap_source_complete,
    write_stk_factor_pro_bootstrap_source_complete,
)
from orchestrator.defs.bootstrap.stk_factor_pro_bootstrap_source import (
    export_stk_factor_pro_bootstrap_month,
    require_stk_factor_pro_bootstrap_source_window,
    validate_stk_factor_pro_bootstrap_approval,
)
from orchestrator.defs.checks.stk_factor_pro import factor_file_sha
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.io.stk_factor_pro_publication import _roots
from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    DEFAULT_LAKE_STAGING_ROOT,
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
    stk_factor_pro_bootstrap_operation_root,
)
from orchestrator.defs.run_contracts import stk_factor_pro as C

__all__ = [
    "bootstrap_stk_factor_pro_history",
    "evaluate_stk_factor_pro_bootstrap_coverage_date",
    "export_stk_factor_pro_bootstrap_month",
    "prepare_stk_factor_pro_bootstrap_coverage_month",
    "process_stk_factor_pro_bootstrap_complete_date",
    "read_stk_factor_pro_bootstrap_publication",
    "read_stk_factor_pro_bootstrap_source_complete",
    "require_stk_factor_pro_bootstrap_source_window",
    "summarize_stk_factor_pro_bootstrap_coverage",
    "update_stk_factor_pro_bootstrap_after_publication",
    "validate_stk_factor_pro_bootstrap_approval",
    "write_stk_factor_pro_bootstrap_coverage_date",
    "write_stk_factor_pro_bootstrap_publication_complete",
    "write_stk_factor_pro_bootstrap_publication_intent",
    "write_stk_factor_pro_bootstrap_source_complete",
]


def _now():
    return datetime.now(ZoneInfo(C.STK_FACTOR_PRO_TIMEZONE))


def process_stk_factor_pro_bootstrap_complete_date(
    connection,
    *,
    lake_root,
    staging_root,
    approval,
    source_complete,
    inputs,
    before_publish=None,
):
    """Internal complete-day callback; errors stop the enclosing named cursor."""

    def guard():
        require_stk_factor_pro_bootstrap_source_window(approval=approval, now=_now())
        if before_publish is None:
            raise ValueError("bootstrap提升必须由已核唯一主入口执行")
        before_publish()

    saved = R.read_stk_factor_pro_bootstrap_source_complete(
        connection,
        staging_root=staging_root,
        approval=approval,
        trade_date=source_complete.trade_date,
    )
    if saved != source_complete:
        raise ValueError("bootstrap完整日回调缺已保存的来源事实")
    if (
        source_complete.trade_date in inputs.closed_dates
        and source_complete.actual_rows
    ):
        raise ValueError("已确认休市日期存在Prod技术因子数据")
    raw, silver = publish_bootstrap_date(
        connection,
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        source_complete=source_complete,
        before_publish=guard,
    )
    result = None
    if source_complete.trade_date not in inputs.closed_dates:
        result = evaluate_stk_factor_pro_bootstrap_coverage_date(
            connection,
            lake_root=lake_root,
            staging_root=staging_root,
            approval=approval,
            inputs=inputs,
            trade_date=source_complete.trade_date,
            source_complete=source_complete,
            raw_audit=raw,
            silver_audit=silver,
            current_publication=None,
        )
        result = write_stk_factor_pro_bootstrap_coverage_date(
            connection,
            lake_root=lake_root,
            staging_root=staging_root,
            approval=approval,
            result=result,
        )
    elif source_complete.actual_rows:
        raise ValueError("已确认休市日期存在Prod技术因子数据")
    return C.StkFactorProBootstrapDateResult(
        source_complete.trade_date,
        source_complete.source_complete_digest,
        raw,
        silver,
        result,
    )


def _current_inputs(entries):
    result = {}
    if type(entries) is not tuple:
        raise ValueError("bootstrap已核发布输入必须是内部冻结tuple")
    for entry in entries:
        if type(entry) is not tuple or len(entry) != 3:
            raise ValueError("bootstrap已核发布须含CurrentPublication及两层audit")
        publication, raw, silver = entry
        if not isinstance(
            publication, C.StkFactorProBootstrapCurrentPublication
        ) or not all(isinstance(a, C.StkFactorProFileAudit) for a in (raw, silver)):
            raise ValueError("bootstrap缺DG已核发布/检查依据")
        if publication.trade_date in result:
            raise ValueError("bootstrap已核发布日期重复")
        result[publication.trade_date] = entry
    return result


def _classify_date(connection, *, lake_root, staging_root, approval, day, trusted):
    source = R.read_stk_factor_pro_bootstrap_source_complete(
        connection, staging_root=staging_root, approval=approval, trade_date=day
    )
    result = R.read_json(
        R.operation_path(
            staging_root, approval, f"coverage/{day.isoformat()}/result.json"
        ),
        C.StkFactorProBootstrapDateCoverage,
    )
    if result is not None and (
        result.operation_id != approval.operation_id
        or result.approval_digest != R.approval_sha(staging_root, approval)
        or result.trade_date != day
    ):
        raise ValueError("bootstrap已有覆盖记录身份不符")
    original = []
    for layer in ("raw", "silver"):
        intent, complete = read_stk_factor_pro_bootstrap_publication(
            lake_root=lake_root,
            staging_root=staging_root,
            approval=approval,
            trade_date=day,
            layer=layer,
        )
        if complete is not None and (
            source is None
            or complete.source_complete_digest != source.source_complete_digest
        ):
            raise ValueError("bootstrap原发布完成与完整日源不符")
        original.append((intent, complete))
    if source is None:
        if (
            any(
                intent is not None or complete is not None
                for intent, complete in original
            )
            or result is not None
        ):
            raise ValueError("bootstrap原导入事实缺完整日源")
        return source, False, False, None
    imported = source.source_empty or all(
        complete is not None for _, complete in original
    )
    publication = result.current_publication if result is not None else None
    entry = trusted.get(day)
    if publication is not None or entry is not None:
        if entry is None:
            raise ValueError("缺少DG已核发布/检查依据，禁止旧Prod恢复")
        if publication is not None and entry[0] != publication:
            raise ValueError("本地复算的已核发布与保存引用不一致")
        if not imported:
            raise ValueError("补数发布不能冒充原bootstrap导入完成")
        pub, raw, silver = entry
        expected_raw = raw_stk_factor_pro_path(lake_root, day.isoformat())
        expected_silver = silver_stock_factor_pro_path(lake_root, day.isoformat())
        if (
            raw.path != expected_raw
            or silver.path != expected_silver
            or raw.trade_date != day
            or silver.trade_date != day
            or raw.layer != "raw"
            or silver.layer != "silver"
            or not raw.passed
            or not silver.passed
            or raw.file_sha256 != pub.raw_file_sha256
            or silver.file_sha256 != pub.silver_file_sha256
            or pub.silver_source_raw_sha256 != raw.file_sha256
            or pub.contract_content_digest != approval.contract_content_digest
            or pub.processing_version != C.STK_FACTOR_PRO_PROCESSING_VERSION
            or factor_file_sha(expected_raw) != raw.file_sha256
            or factor_file_sha(expected_silver) != silver.file_sha256
        ):
            raise ValueError("bootstrap当前发布依据不对应两层正式文件")
        return source, True, False, entry
    if imported:
        if source.source_empty:
            if any(
                path.exists()
                for path in (
                    raw_stk_factor_pro_path(lake_root, day.isoformat()),
                    silver_stock_factor_pro_path(lake_root, day.isoformat()),
                )
            ):
                raise ValueError("bootstrap空源目标已出现文件但缺合法补数依据")
        else:
            for intent, complete in original:
                if (
                    not complete.audit.path.is_file()
                    or factor_file_sha(complete.audit.path)
                    != complete.actual_file_sha256
                ):
                    raise ValueError("bootstrap正式文件改变或缺失且无合法补数凭据")
            if original[1][0].raw_file_sha256 != original[0][1].actual_file_sha256:
                raise ValueError("bootstrap原Silver不对应当前Raw")
        return source, True, False, None
    return source, False, True, None


def _run_stk_factor_pro_bootstrap(
    connection,
    *,
    lake_root,
    staging_root,
    operation_id,
    instance,
    prod_postgres,
    current_publications=(),
):
    """Internal dependency-injected orchestration; never an operator path override."""
    _roots(lake_root, staging_root)
    require_stk_factor_pro_no_other_active_runs(instance)
    root = stk_factor_pro_bootstrap_operation_root(staging_root, operation_id)
    approval = R.read_json(root / "approval.json", C.StkFactorProBootstrapApproval)
    if approval is None or approval.operation_id != operation_id:
        raise ValueError("bootstrap缺本operation管理员批准记录")
    counts, _, _ = S._approved_inputs(
        connection, staging_root=staging_root, approval=approval
    )
    trusted = _current_inputs(current_publications)
    days = tuple(
        approval.start_trade_date + timedelta(days=i)
        for i in range((approval.end_trade_date - approval.start_trade_date).days + 1)
    )
    if set(trusted) - set(days):
        raise ValueError("bootstrap已核当前发布越出批准日期范围")
    classified = {
        day: _classify_date(
            connection,
            lake_root=lake_root,
            staging_root=staging_root,
            approval=approval,
            day=day,
            trusted=trusted,
        )
        for day in days
    }
    checked = False

    def before_publish():
        nonlocal checked
        require_stk_factor_pro_bootstrap_source_window(approval=approval, now=_now())
        if not checked:
            require_stk_factor_pro_no_other_active_runs(instance)
            checked = True

    imported = {day for day, (_, valid, _, _) in classified.items() if valid}
    current = set()
    for month in approval.month_limits:
        with R.resource_cleanup(
            lambda: release_stk_factor_pro_bootstrap_coverage_month(connection)
        ):
            inputs = prepare_stk_factor_pro_bootstrap_coverage_month(
                connection,
                lake_root=lake_root,
                staging_root=staging_root,
                approval=approval,
                month=month,
            )
            if any(counts[day] for day in inputs.closed_dates):
                raise ValueError("已确认休市日期存在Prod技术因子数据")
            if inputs.open_dates:
                instance.add_dynamic_partitions(
                    C.STK_FACTOR_PRO_PARTITIONS,
                    [d.isoformat() for d in inputs.open_dates],
                )
            month_days = tuple(
                d for d in days if month.month_start <= d < month.month_end_exclusive
            )
            pending = tuple(d for d in month_days if classified[d][0] is None)
            recover = tuple(d for d in month_days if classified[d][2])
            if recover:
                # This branch may restore business files, so its source maintenance
                # conditions remain mandatory even though complete fragments exist.
                S.preflight_stk_factor_pro_bootstrap_source(
                    prod_postgres=prod_postgres,
                    connection=connection,
                    staging_root=staging_root,
                    approval=approval,
                    month=month,
                    selected_dates=tuple(sorted(set(pending + recover))),
                )

            def complete_date(source, *, inputs=inputs):
                value = process_stk_factor_pro_bootstrap_complete_date(
                    connection,
                    lake_root=lake_root,
                    staging_root=staging_root,
                    approval=approval,
                    source_complete=source,
                    inputs=inputs,
                    before_publish=before_publish,
                )
                imported.add(source.trade_date)
                current.add(source.trade_date)
                return value

            for day in month_days:
                source, _valid, _needs_restore, entry = classified[day]
                if source is None:
                    continue
                if entry is not None:
                    publication, raw, silver = entry
                    value = evaluate_stk_factor_pro_bootstrap_coverage_date(
                        connection,
                        lake_root=lake_root,
                        staging_root=staging_root,
                        approval=approval,
                        inputs=inputs,
                        trade_date=day,
                        source_complete=source,
                        raw_audit=raw,
                        silver_audit=silver,
                        current_publication=publication,
                    )
                    write_stk_factor_pro_bootstrap_coverage_date(
                        connection,
                        lake_root=lake_root,
                        staging_root=staging_root,
                        approval=approval,
                        result=value,
                    )
                    current.add(day)
                else:
                    complete_date(source)
            if pending:
                export_stk_factor_pro_bootstrap_month(
                    prod_postgres=prod_postgres,
                    connection=connection,
                    staging_root=staging_root,
                    approval=approval,
                    month=month,
                    selected_dates=pending,
                    on_complete_date=complete_date,
                )
    # Reprepare once at the end. Changed local basis requires bounded local
    # recomputation, never a fresh Prod query or an unbounded stability loop.
    final_inputs = []
    for month in approval.month_limits:
        with R.resource_cleanup(
            lambda: release_stk_factor_pro_bootstrap_coverage_month(connection)
        ):
            inputs = prepare_stk_factor_pro_bootstrap_coverage_month(
                connection,
                lake_root=lake_root,
                staging_root=staging_root,
                approval=approval,
                month=month,
            )
            for day in inputs.natural_dates:
                if day not in current or day in inputs.closed_dates:
                    continue
                source, _, _, entry = _classify_date(
                    connection,
                    lake_root=lake_root,
                    staging_root=staging_root,
                    approval=approval,
                    day=day,
                    trusted=trusted,
                )
                if entry is not None:
                    publication, raw, silver = entry
                elif source.source_empty:
                    publication, raw, silver = None, None, None
                else:
                    publication = None
                    raw = read_stk_factor_pro_bootstrap_publication(
                        lake_root=lake_root,
                        staging_root=staging_root,
                        approval=approval,
                        trade_date=day,
                        layer="raw",
                    )[1].audit
                    silver = read_stk_factor_pro_bootstrap_publication(
                        lake_root=lake_root,
                        staging_root=staging_root,
                        approval=approval,
                        trade_date=day,
                        layer="silver",
                    )[1].audit
                value = evaluate_stk_factor_pro_bootstrap_coverage_date(
                    connection,
                    lake_root=lake_root,
                    staging_root=staging_root,
                    approval=approval,
                    inputs=inputs,
                    trade_date=day,
                    source_complete=source,
                    raw_audit=raw,
                    silver_audit=silver,
                    current_publication=publication,
                )
                write_stk_factor_pro_bootstrap_coverage_date(
                    connection,
                    lake_root=lake_root,
                    staging_root=staging_root,
                    approval=approval,
                    result=value,
                )
            final_inputs.append(inputs)
    return summarize_stk_factor_pro_bootstrap_coverage(
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        verified_import_dates=tuple(sorted(imported)),
        verified_current_dates=tuple(sorted(current)),
        inputs=tuple(final_inputs),
    )


def bootstrap_stk_factor_pro_history(
    *, operation_id, instance, prod_postgres, lake_root
):
    """Formal entry: fixed formal roots and the caller's existing instance only."""
    from pathlib import Path

    lake_root.ensure_available_for_run()
    if lake_root.root() != Path(DEFAULT_LAKE_ROOT):
        raise ValueError("正式bootstrap入口不接受任意Lake根")
    with R.resource_context(connect_configured_duckdb()) as connection:
        return _run_stk_factor_pro_bootstrap(
            connection,
            lake_root=lake_root.root(),
            staging_root=Path(DEFAULT_LAKE_STAGING_ROOT),
            operation_id=operation_id,
            instance=instance,
            prod_postgres=prod_postgres,
        )
