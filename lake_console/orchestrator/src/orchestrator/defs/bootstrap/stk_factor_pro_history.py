"""Single approved Prod bootstrap entry; daily jobs and event readers live elsewhere."""

from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
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


_LOGGER = logging.getLogger(__name__)


class _BootstrapProgress:
    """Synchronous summaries only; durable records remain the source of truth."""

    def __init__(self, operation_id):
        self.started = time.monotonic()
        self.done = set()
        self.warned = False
        self.fields = {
            "operation_id": operation_id,
            "attempt_id": None,
            "month": None,
            "stage": "核对批准和输入",
            "event": None,
            "batch_no": None,
            "batch_rows": None,
            "saved_rows": None,
            "completed_dates": 0,
            "total_dates": None,
            "trade_date": None,
            "raw_rows": None,
            "silver_rows": None,
            "coverage_state": None,
            "reused_source_rows": None,
            "elapsed_seconds": 0.0,
            "updated_at": None,
            "outcome": None,
        }

    def configure(self, *, total_dates, reused_source_rows):
        self.fields.update(
            total_dates=total_dates, reused_source_rows=reused_source_rows
        )

    def remember(
        self, day, result, source, *, raw_sha, silver_sha, raw_rows, silver_rows
    ):
        if result is not None and (
            result.source_complete_digest == source.source_complete_digest
            and result.source_rows == source.actual_rows
            and result.raw_file_sha256 == raw_sha
            and result.silver_file_sha256 == silver_sha
            and result.raw_rows == raw_rows
            and result.silver_rows == silver_rows
            and result.import_complete
        ):
            self.done.add(day)

    def set_stage(self, stage, *, trade_date=None):
        self.fields["stage"] = stage
        if trade_date is not None:
            self.fields["trade_date"] = trade_date.isoformat()

    def emit(self, event, **values):
        self.fields.update(
            values,
            event=event,
            completed_dates=len(self.done),
            elapsed_seconds=round(time.monotonic() - self.started, 3),
            updated_at=_now().isoformat(),
        )
        try:
            _LOGGER.info(
                "股票技术因子bootstrap进度 %s",
                json.dumps(self.fields, ensure_ascii=False, sort_keys=True),
                extra={"stk_factor_pro_bootstrap": dict(self.fields)},
            )
        except Exception:  # noqa: BLE001 - approved logs must not interrupt business work
            # Observability must not retry or undo business data. Do not use a
            # failing handler recursively, or print potentially sensitive errors.
            if not self.warned:
                self.warned = True
                try:
                    sys.stderr.write(
                        "bootstrap进度日志输出失败，业务继续；请检查日志配置。\n"
                    )
                except Exception:  # noqa: BLE001 - finite stderr fallback is observation only
                    return

    def month_started(self, month, *, selected_count, approved_rows, mode):
        self.emit(
            "month_started",
            month=month.month_start.strftime("%Y-%m"),
            stage="开始本月处理",
            attempt_id=None,
            saved_rows=None,
            batch_no=None,
            batch_rows=None,
            trade_date=None,
            raw_rows=None,
            silver_rows=None,
            coverage_state=None,
            outcome=mode,
            selected_date_count=selected_count,
            approved_rows=approved_rows,
            row_upper_bound=month.row_upper_bound,
            fetch_rows=C.STK_FACTOR_PRO_BOOTSTRAP_FETCH_ROWS,
        )

    def start_attempt(self, attempt_id):
        self.fields.update(
            attempt_id=attempt_id, saved_rows=0, batch_no=0, batch_rows=0
        )

    def batch_saved(self, *, batch_no, rows, trade_date):
        self.emit(
            "batch_saved",
            stage="源片段已保存并读回",
            batch_no=batch_no,
            batch_rows=rows,
            saved_rows=self.fields["saved_rows"] + rows,
            trade_date=trade_date.isoformat(),
            raw_rows=None,
            silver_rows=None,
            coverage_state=None,
            outcome="源已保存，完整日期另行处理",
        )

    def date_completed(self, *, day, raw, silver, coverage):
        self.done.add(day)
        state = (
            None
            if coverage is None
            else (
                "unknown"
                if coverage.coverage_complete is None
                else "complete"
                if coverage.coverage_complete
                else "incomplete"
            )
        )
        self.emit(
            "date_completed",
            stage="完整日期处理完成",
            trade_date=day.isoformat(),
            raw_rows=0 if raw is None else raw.row_count,
            silver_rows=0 if silver is None else silver.row_count,
            coverage_state=state,
            outcome="源0且无业务文件，已完成分类"
            if raw is None
            else "两层及覆盖记录已保存",
        )

    def finish(self, summary):
        state = (
            "unknown"
            if summary.all_expected_present is None
            else ("complete" if summary.all_expected_present else "incomplete")
        )
        self.emit(
            "operation_finished",
            stage="资源已关闭，处理结束",
            month=None,
            trade_date=None,
            raw_rows=summary.current_raw_rows,
            silver_rows=summary.current_silver_rows,
            coverage_state=state,
            outcome="物理导入和统计完成；股票覆盖单独说明",
            next_action="按覆盖结果检查缺口和未知依据",
        )

    def failed(self, primary):
        try:
            self.emit(
                "operation_failed",
                outcome="本次处理失败，已保存文件保留",
                reason=f"{self.fields['stage']}失败（{type(primary).__name__}）",
                next_action="查看原始异常及已有记录，处理原因后重新执行",
            )
        except BaseException as notification:  # noqa: BLE001 - preserve the original business failure
            primary.add_note(
                f"bootstrap失败摘要同时中断：{type(notification).__name__}"
            )


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
    check_space,
    verification=None,
    progress=None,
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
    if progress is not None:
        progress.set_stage("发布本日Raw和Silver", trade_date=source_complete.trade_date)
    raw, silver = publish_bootstrap_date(
        connection,
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        source_complete=source_complete,
        before_publish=guard,
        check_space=check_space,
        verification=verification,
    )
    result = None
    if progress is not None:
        progress.set_stage("计算并保存本日覆盖", trade_date=source_complete.trade_date)
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
            check_space=check_space,
        )
        result = write_stk_factor_pro_bootstrap_coverage_date(
            connection,
            lake_root=lake_root,
            staging_root=staging_root,
            approval=approval,
            result=result,
            check_space=check_space,
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


def _classify_date(
    connection, *, lake_root, staging_root, approval, day, trusted, progress=None
):
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
        if progress is not None:
            progress.remember(
                day,
                result,
                source,
                raw_sha=raw.file_sha256,
                silver_sha=silver.file_sha256,
                raw_rows=raw.row_count,
                silver_rows=silver.row_count,
            )
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
        if progress is not None:
            progress.remember(
                day,
                result,
                source,
                raw_sha=None
                if source.source_empty
                else original[0][1].actual_file_sha256,
                silver_sha=None
                if source.source_empty
                else original[1][1].actual_file_sha256,
                raw_rows=source.actual_rows,
                silver_rows=source.actual_rows,
            )
        return source, True, False, None
    return source, False, True, None


def _bootstrap_space_check(
    connection, *, lake_root, staging_root, approval, counts, classified
):
    """One operation's remaining disk needs; no extra data reads or durable state."""
    temp_directory = Path(
        connection.execute("SELECT current_setting('temp_directory')").fetchone()[0]
    )
    pending_sources = {
        month.month_start: sum(
            counts[d]
            for d, (source, _, _, _) in classified.items()
            if source is None and month.month_start <= d < month.month_end_exclusive
        )
        for month in approval.month_limits
    }
    remaining_layers, working = {}, {}
    working_by_month = {}
    unpublished_layers = set()
    remaining_dates = set(counts)
    for day, (source, valid, _, entry) in classified.items():
        rows = entry[1].row_count if entry is not None else counts[day]
        working[day] = (rows, rows)
        working_by_month.setdefault((day.year, day.month), []).append(day)
        if valid or rows == 0:
            continue
        for layer in ("raw", "silver"):
            intent, complete = read_stk_factor_pro_bootstrap_publication(
                lake_root=lake_root,
                staging_root=staging_root,
                approval=approval,
                trade_date=day,
                layer=layer,
            )
            if complete is not None:
                if factor_file_sha(complete.audit.path) != complete.actual_file_sha256:
                    raise ValueError("bootstrap空间核验发现已有正式文件身份改变")
            else:
                unpublished_layers.add((day, layer))
                # Only a verified original intent may prove an existing file
                # already satisfies this disk need; completion is still pending.
                satisfied = False
                if intent is not None:
                    target = (
                        raw_stk_factor_pro_path
                        if layer == "raw"
                        else silver_stock_factor_pro_path
                    )(lake_root, day.isoformat())
                    candidate = R.operation_path(
                        staging_root, approval, intent.candidate.relative_path
                    )
                    satisfied = (
                        target.is_file()
                        and factor_file_sha(target) == intent.expected_file_sha256
                    ) or (
                        candidate.is_file()
                        and factor_file_sha(candidate) == intent.candidate.file_sha256
                    )
                if not satisfied:
                    remaining_layers[day, layer] = rows
    remaining_layer_total_rows = sum(remaining_layers.values())
    remaining_layer_file_count = len(remaining_layers)
    observed = {"row": 4178, "file": 4 * 1024**2, "record": 1024**2}
    record_sizes = {}
    record_group_sizes = {}
    known_record_bytes = 0
    active_month = None

    def check_space(
        stage,
        *,
        path,
        trade_date=None,
        layer=None,
        rows=None,
        event=None,
        month_start=None,
    ):
        nonlocal \
            active_month, \
            known_record_bytes, \
            remaining_layer_total_rows, \
            remaining_layer_file_count
        if month_start is not None:
            active_month = month_start
        if path.is_file():
            size = path.stat().st_size
            if path.suffix == ".json":
                previous_day, previous_size = record_sizes.get(path, (trade_date, 0))
                if previous_day != trade_date:
                    raise ValueError("bootstrap空间记录日期归属改变")
                record_sizes[path] = (trade_date, size)
                delta = size - previous_size
                record_group_sizes[trade_date] = (
                    record_group_sizes.get(trade_date, 0) + delta
                )
                if trade_date is None or trade_date in remaining_dates:
                    known_record_bytes += delta
                observed["record"] = max(
                    observed["record"], record_group_sizes[trade_date]
                )
            elif rows:
                observed["row"] = max(
                    observed["row"],
                    (max(0, size - observed["file"]) + rows - 1) // rows,
                )
        if event == "final_statistics":
            active_month = None
            remaining_dates.update(counts)
            known_record_bytes = sum(record_group_sizes.values())
        if event == "source_saved":
            if (
                type(rows) is not int
                or rows < 0
                or month_start not in pending_sources
                or rows > pending_sources[month_start]
            ):
                raise ValueError("bootstrap已保存源行数不能重复扣减或越出批准量")
            pending_sources[month_start] -= rows
        elif event in ("candidate_verified", "publication_verified"):
            removed = remaining_layers.pop((trade_date, layer), None)
            if removed is not None:
                remaining_layer_total_rows -= removed
                remaining_layer_file_count -= 1
            if event == "publication_verified":
                unpublished_layers.discard((trade_date, layer))
        elif event == "date_completed":
            if trade_date in remaining_dates:
                known_record_bytes -= record_group_sizes.get(trade_date, 0)
                remaining_dates.remove(trade_date)
        if trade_date is not None and rows is not None:
            prior_work = working[trade_date]
            working[trade_date] = (max(prior_work[0], rows), max(prior_work[1], rows))
        if trade_date is not None:
            work_rows = working[trade_date]
        else:
            selected_days = (
                working
                if active_month is None
                else working_by_month.get((active_month.year, active_month.month), ())
            )
            applicable = [
                working[day] for day in selected_days if day in remaining_dates
            ]
            work_rows = max(applicable, default=(0, 0))
        estimate = R.estimate_bootstrap_space(
            pending_source_rows_by_month=tuple(pending_sources.values()),
            remaining_layer_rows=(),
            remaining_layer_totals=(
                remaining_layer_total_rows,
                remaining_layer_file_count,
            ),
            work_rows=work_rows,
            pending_fetch_rows=min(
                C.STK_FACTOR_PRO_BOOTSTRAP_FETCH_ROWS,
                pending_sources.get(
                    active_month, max(pending_sources.values(), default=0)
                ),
            ),
            remaining_date_count=len(remaining_dates),
            statistics_only=not any(pending_sources.values())
            and not unpublished_layers,
            observed_row_bytes=observed["row"],
            observed_file_overhead=observed["file"],
            observed_record_bytes=observed["record"],
        )
        estimate = replace(
            estimate, record_bytes=max(0, estimate.record_bytes - known_record_bytes)
        )
        # A record just persisted is an observation, not another future write.
        # All following read/write boundaries recheck actual free space.
        if event == "record_saved":
            return estimate
        R.require_bootstrap_space(
            operation_id=approval.operation_id,
            stage=stage,
            estimate=estimate,
            staging_root=staging_root,
            temp_directory=temp_directory,
        )
        return estimate

    return check_space


def _execute_stk_factor_pro_bootstrap(
    connection,
    *,
    lake_root,
    staging_root,
    operation_id,
    instance,
    prod_postgres,
    current_publications=(),
    progress,
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
            progress=progress,
        )
        for day in days
    }
    progress.configure(
        total_dates=len(days),
        reused_source_rows=sum(
            source.actual_rows
            for source, _, _, _ in classified.values()
            if source is not None
        ),
    )
    check_space = _bootstrap_space_check(
        connection,
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        counts=counts,
        classified=classified,
    )
    check_space("读取前核磁盘空间", path=root)
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
        check_space("准备本月工作前", path=root, month_start=month.month_start)
        verification = R.BootstrapFragmentVerification(
            connection, staging_root=staging_root, approval=approval, month=month
        )
        with R.resource_cleanup(
            verification.close,
            lambda: release_stk_factor_pro_bootstrap_coverage_month(connection),
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
            for day in inputs.closed_dates:
                source, valid, _, _ = classified[day]
                if valid and source is not None and source.source_empty:
                    progress.done.add(day)
            progress.month_started(
                month,
                selected_count=len(pending),
                approved_rows=sum(counts[d] for d in month_days),
                mode="读取来源并导入"
                if pending
                else "恢复业务文件"
                if recover
                else "仅本地统计",
            )
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

            def complete_date(source, *, inputs=inputs, verification=verification):
                value = process_stk_factor_pro_bootstrap_complete_date(
                    connection,
                    lake_root=lake_root,
                    staging_root=staging_root,
                    approval=approval,
                    source_complete=source,
                    inputs=inputs,
                    before_publish=before_publish,
                    check_space=check_space,
                    verification=verification,
                    progress=progress,
                )
                S._validate_date_result(source, value)
                imported.add(source.trade_date)
                current.add(source.trade_date)
                progress.date_completed(
                    day=source.trade_date,
                    raw=value.raw_audit,
                    silver=value.silver_audit,
                    coverage=value.coverage,
                )
                check_space(
                    "完整日期处理完成",
                    path=root,
                    trade_date=source.trade_date,
                    rows=source.actual_rows,
                    event="date_completed",
                )
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
                        check_space=check_space,
                    )
                    write_stk_factor_pro_bootstrap_coverage_date(
                        connection,
                        lake_root=lake_root,
                        staging_root=staging_root,
                        approval=approval,
                        result=value,
                        check_space=check_space,
                    )
                    current.add(day)
                    progress.date_completed(
                        day=day, raw=raw, silver=silver, coverage=value
                    )
                    check_space(
                        "当前日期统计完成",
                        path=root,
                        trade_date=day,
                        rows=raw.row_count,
                        event="date_completed",
                    )
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
                    check_space=check_space,
                    verification=verification,
                    progress=progress,
                )
    # Reprepare once at the end. Changed local basis requires bounded local
    # recomputation, never a fresh Prod query or an unbounded stability loop.
    check_space("最终统计准备前", path=root, event="final_statistics")
    final_inputs = []
    for month in approval.month_limits:
        check_space("准备本月工作前", path=root, month_start=month.month_start)
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
                    check_space=check_space,
                )
                write_stk_factor_pro_bootstrap_coverage_date(
                    connection,
                    lake_root=lake_root,
                    staging_root=staging_root,
                    approval=approval,
                    result=value,
                    check_space=check_space,
                )
                check_space(
                    "最终本日统计完成",
                    path=root,
                    trade_date=day,
                    rows=value.raw_rows,
                    event="date_completed",
                )
            final_inputs.append(inputs)
    return summarize_stk_factor_pro_bootstrap_coverage(
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        verified_import_dates=tuple(sorted(imported)),
        verified_current_dates=tuple(sorted(current)),
        inputs=tuple(final_inputs),
        check_space=check_space,
    )


def _run_stk_factor_pro_bootstrap(
    connection,
    *,
    lake_root,
    staging_root,
    operation_id,
    instance,
    prod_postgres,
    current_publications=(),
    progress=None,
):
    """Borrow a caller connection; only the formal owner emits final success."""
    observer = progress if progress is not None else _BootstrapProgress(operation_id)
    try:
        return _execute_stk_factor_pro_bootstrap(
            connection,
            lake_root=lake_root,
            staging_root=staging_root,
            operation_id=operation_id,
            instance=instance,
            prod_postgres=prod_postgres,
            current_publications=current_publications,
            progress=observer,
        )
    except BaseException as error:
        if progress is None:
            observer.failed(error)
        raise


def bootstrap_stk_factor_pro_history(
    *, operation_id, instance, prod_postgres, lake_root
):
    """Formal entry: fixed formal roots and the caller's existing instance only."""
    progress = _BootstrapProgress(operation_id)
    try:
        lake_root.ensure_available_for_run()
        if lake_root.root() != Path(DEFAULT_LAKE_ROOT):
            raise ValueError("正式bootstrap入口不接受任意Lake根")
        with R.resource_context(connect_configured_duckdb()) as connection:
            result = _run_stk_factor_pro_bootstrap(
                connection,
                lake_root=lake_root.root(),
                staging_root=Path(DEFAULT_LAKE_STAGING_ROOT),
                operation_id=operation_id,
                instance=instance,
                prod_postgres=prod_postgres,
                progress=progress,
            )
            progress.set_stage("关闭DuckDB连接")
    except BaseException as error:
        progress.failed(error)
        raise
    progress.finish(result)
    return result
