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
    compute_stk_factor_pro_bootstrap_coverage_date,
    evaluate_stk_factor_pro_bootstrap_coverage_date,
    new_stk_factor_pro_bootstrap_coverage_totals,
    prepare_stk_factor_pro_bootstrap_coverage_date,
    prepare_stk_factor_pro_bootstrap_coverage_month,
    read_stk_factor_pro_bootstrap_coverage_date,
    refresh_stk_factor_pro_bootstrap_date_contribution,
    release_stk_factor_pro_bootstrap_coverage_inputs,
    release_stk_factor_pro_bootstrap_coverage_month,
    require_stk_factor_pro_bootstrap_coverage_identities,
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
from orchestrator.defs.checks.stk_factor_pro import (
    factor_file_identity,
    factor_known_file_sha,
    release_stk_factor_pro_audit_relations,
)
from orchestrator.defs.duckdb_connection import connect_configured_duckdb
from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.stk_factor_pro_candidates import (
    BOOTSTRAP_DAY_SOURCE,
    DAY_PRIOR,
    RAW_EXPECTED,
    RAW_MATCHED_KEYS,
    SILVER_EXPECTED,
)
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
            "source_rows": None,
            "raw_rows": None,
            "silver_rows": None,
            "coverage_state": None,
            "reused_source_rows": None,
            "elapsed_seconds": 0.0,
            "updated_at": None,
            "outcome": None,
            "space_estimate_stage": None,
            "space_initial_estimate": None,
            "space_latest_estimate": None,
            "space_initial_row_bytes": C.STK_FACTOR_PRO_ESTIMATED_ROW_BYTES,
            "space_observed_row_bytes": None,
            "space_initial_record_bytes": C.STK_FACTOR_PRO_ESTIMATED_RECORD_BYTES,
            "space_observed_record_bytes": None,
            "space_latest_observation": None,
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
        if event != "date_completed":
            values["source_rows"] = None
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

    def date_completed(self, *, day, source_rows, raw, silver, coverage):
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
            source_rows=source_rows,
            raw_rows=0 if raw is None else raw.row_count,
            silver_rows=0 if silver is None else silver.row_count,
            coverage_state=state,
            outcome="源0且无业务文件，已完成分类"
            if raw is None
            else "两层及覆盖记录已保存",
        )

    def observe_space(self, *, stage, estimate, observed, observation=None):
        """Attach existing arithmetic and file observations; never log or read IO."""
        values = {
            "source_bytes": estimate.source_bytes,
            "candidate_bytes": estimate.candidate_bytes,
            "temp_bytes": estimate.temp_bytes,
            "record_bytes": estimate.record_bytes,
        }
        if self.fields["space_initial_estimate"] is None:
            self.fields["space_initial_estimate"] = dict(values)
        self.fields.update(
            space_estimate_stage=stage,
            space_latest_estimate=values,
            space_observed_row_bytes=observed["row"],
            space_observed_record_bytes=observed["record"],
        )
        if observation is not None:
            self.fields["space_latest_observation"] = observation

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


def _require_bootstrap_coverage_identities(
    *,
    lake_root,
    prepared,
    known_records,
    entry,
):
    try:
        require_stk_factor_pro_bootstrap_coverage_identities(
            lake_root=lake_root, prepared=prepared, known_records=known_records
        )
    except (ValueError, OSError):
        entry["coverage_record_current"] = False
        entry["current_files_verified"] = prepared["current_files_verified"]
        entry["unknown_reason"] = "覆盖依据或正式文件身份发生变化"
        raise


def _prepare_bootstrap_date_coverage(
    *,
    lake_root,
    approval,
    approval_digest,
    inputs,
    basis_inputs,
    source,
    raw,
    silver,
    publication,
    date_results,
    known_records,
):
    entry = date_results[source.trade_date]
    prepared = prepare_stk_factor_pro_bootstrap_coverage_date(
        approval=approval,
        approval_digest=approval_digest,
        inputs=inputs,
        basis_inputs=basis_inputs,
        source_complete=source,
        raw_audit=raw,
        silver_audit=silver,
        current_publication=publication,
        previous_result=entry["persisted_result"],
    )
    entry["coverage_record_current"] = prepared["reusable_result"] is not None
    entry["unknown_reason"] = (
        None if entry["coverage_record_current"] else "本日覆盖统计尚未完成"
    )
    _require_bootstrap_coverage_identities(
        lake_root=lake_root, prepared=prepared, known_records=known_records, entry=entry
    )
    return prepared


def _save_prepared_bootstrap_coverage(
    connection,
    *,
    lake_root,
    staging_root,
    approval,
    prepared,
    raw_relation,
    date_results,
    check_space,
    known_records,
):
    entry = date_results[prepared["trade_date"]]
    calculated = None
    if prepared["reusable_result"] is None:
        calculated = compute_stk_factor_pro_bootstrap_coverage_date(
            connection,
            lake_root=lake_root,
            staging_root=staging_root,
            approval=approval,
            prepared=prepared,
            raw_relation=raw_relation,
            diagnostic_run=None,
            check_space=check_space,
            known_records=known_records,
        )
        _require_bootstrap_coverage_identities(
            lake_root=lake_root,
            prepared=prepared,
            known_records=known_records,
            entry=entry,
        )
    result = evaluate_stk_factor_pro_bootstrap_coverage_date(
        prepared=prepared, calculated=calculated
    )
    entry["computed_result"] = result
    return write_stk_factor_pro_bootstrap_coverage_date(
        connection,
        lake_root=lake_root,
        staging_root=staging_root,
        approval=approval,
        result=result,
        previous_result=entry["persisted_result"],
        previous_result_digest=entry["persisted_result_digest"],
        date_results=date_results,
        check_space=check_space,
        known_records=known_records,
    )[0]


def _complete_existing_bootstrap_coverage(
    connection,
    *,
    lake_root,
    staging_root,
    approval,
    inputs,
    basis_inputs,
    entry,
    date_results,
    check_space,
    known_records,
):
    source = entry["source_complete"]
    prepared = _prepare_bootstrap_date_coverage(
        lake_root=lake_root,
        approval=approval,
        approval_digest=known_records[
            R.operation_path(staging_root, approval, "approval.json")
        ][1],
        inputs=inputs,
        basis_inputs=basis_inputs,
        source=source,
        raw=entry["raw_audit"],
        silver=entry["silver_audit"],
        publication=entry["current_publication"],
        date_results=date_results,
        known_records=known_records,
    )
    arguments = {
        "lake_root": lake_root,
        "staging_root": staging_root,
        "approval": approval,
        "prepared": prepared,
        "date_results": date_results,
        "check_space": check_space,
        "known_records": known_records,
    }
    if (
        prepared["reusable_result"] is not None
        or prepared["unknown_input_kinds"]
        or prepared["raw_audit"] is None
    ):
        return _save_prepared_bootstrap_coverage(
            connection, raw_relation=None, **arguments
        )
    relation = "stk_factor_pro_bootstrap_current_raw_codes"
    with R.resource_cleanup(
        lambda: connection.execute(f"DROP TABLE IF EXISTS {relation}")
    ):
        connection.execute(
            f"CREATE TEMP TABLE {relation} AS SELECT ts_code,trade_date "
            f"FROM {read_parquet(prepared['raw_audit'].path, hive_partitioning=False)}"
        )
        return _save_prepared_bootstrap_coverage(
            connection, raw_relation=relation, **arguments
        )


def process_stk_factor_pro_bootstrap_complete_date(
    connection,
    *,
    lake_root,
    staging_root,
    approval,
    source_complete,
    source_record_sha256,
    source_relation,
    inputs,
    basis_inputs,
    before_publish=None,
    check_space,
    progress=None,
    known_records,
    date_results,
):
    """Internal complete-day callback; errors stop the enclosing named cursor."""

    def guard():
        require_stk_factor_pro_bootstrap_source_window(approval=approval, now=_now())
        if before_publish is None:
            raise ValueError("bootstrap提升必须由已核唯一主入口执行")
        before_publish()

    releases = tuple(
        lambda name=name: connection.execute(f"DROP TABLE IF EXISTS {name}")
        for name in (SILVER_EXPECTED, RAW_EXPECTED, RAW_MATCHED_KEYS, DAY_PRIOR)
    ) + (lambda: release_stk_factor_pro_audit_relations(connection),)
    with R.resource_cleanup(*releases):
        if (
            source_complete.trade_date in inputs.closed_dates
            and source_complete.actual_rows
        ):
            raise ValueError("已确认休市日期存在Prod技术因子数据")
        if progress is not None:
            progress.set_stage(
                "发布本日Raw和Silver", trade_date=source_complete.trade_date
            )
        raw, silver = publish_bootstrap_date(
            connection,
            lake_root=lake_root,
            staging_root=staging_root,
            approval=approval,
            source_complete=source_complete,
            source_record_sha256=source_record_sha256,
            source_relation=source_relation,
            before_publish=guard,
            check_space=check_space,
            known_records=known_records,
            date_results=date_results,
        )
        result = None
        if progress is not None:
            progress.set_stage(
                "计算并保存本日覆盖", trade_date=source_complete.trade_date
            )
        if source_complete.trade_date not in inputs.closed_dates:
            prepared = _prepare_bootstrap_date_coverage(
                lake_root=lake_root,
                approval=approval,
                approval_digest=known_records[
                    R.operation_path(staging_root, approval, "approval.json")
                ][1],
                inputs=inputs,
                basis_inputs=basis_inputs,
                source=source_complete,
                raw=raw,
                silver=silver,
                publication=None,
                date_results=date_results,
                known_records=known_records,
            )
            result = _save_prepared_bootstrap_coverage(
                connection,
                lake_root=lake_root,
                staging_root=staging_root,
                approval=approval,
                prepared=prepared,
                raw_relation=RAW_EXPECTED if raw is not None else None,
                date_results=date_results,
                check_space=check_space,
                known_records=known_records,
            )
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
    connection,
    *,
    lake_root,
    staging_root,
    approval,
    day,
    trusted,
    progress=None,
    known_records,
):
    source = R.read_stk_factor_pro_bootstrap_source_complete(
        connection,
        staging_root=staging_root,
        approval=approval,
        trade_date=day,
        known_records=known_records,
    )
    result = read_stk_factor_pro_bootstrap_coverage_date(
        connection,
        staging_root=staging_root,
        approval=approval,
        approval_digest=known_records[
            R.operation_path(staging_root, approval, "approval.json")
        ][1],
        source_complete=source,
        trade_date=day,
        known_records=known_records,
    )
    original = []
    for layer in ("raw", "silver"):
        intent, complete = read_stk_factor_pro_bootstrap_publication(
            lake_root=lake_root,
            staging_root=staging_root,
            approval=approval,
            trade_date=day,
            layer=layer,
            known_records=known_records,
        )
        if complete is not None and (
            source is None
            or complete.source_complete_digest != source.source_complete_digest
        ):
            raise ValueError("bootstrap原发布完成与完整日源不符")
        original.append((intent, complete))

    def date_result(valid, needs_restore, entry):
        source_path = R.operation_path(
            staging_root,
            approval,
            f"source/dates/{day.isoformat()}/source-complete.json",
        )
        result_path = R.operation_path(
            staging_root, approval, f"coverage/{day.isoformat()}/result.json"
        )
        raw_complete, silver_complete = (item[1] for item in original)
        return {
            "source_complete": source,
            "source_record_sha256": known_records[source_path][1],
            "raw_complete": raw_complete,
            "silver_complete": silver_complete,
            "raw_audit": entry[1]
            if entry is not None
            else (None if raw_complete is None else raw_complete.audit),
            "silver_audit": entry[2]
            if entry is not None
            else (None if silver_complete is None else silver_complete.audit),
            "current_publication": None if entry is None else entry[0],
            "current_files_verified": valid,
            "needs_restore": needs_restore,
            "import_complete": source is not None
            and (
                source.source_empty
                or all(complete is not None for _, complete in original)
            ),
            "replaced_layers": set(),
            "persisted_result": result,
            "persisted_result_digest": known_records[result_path][1],
            "computed_result": None,
            "coverage_record_current": False,
            "unknown_reason": None,
            "previous_contribution": None,
        }

    if source is None:
        if (
            any(
                intent is not None or complete is not None
                for intent, complete in original
            )
            or result is not None
        ):
            raise ValueError("bootstrap原导入事实缺完整日源")
        return date_result(False, False, None)
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
            or factor_known_file_sha(expected_raw, known_records=known_records)
            != raw.file_sha256
            or factor_known_file_sha(expected_silver, known_records=known_records)
            != silver.file_sha256
        ):
            raise ValueError("bootstrap当前发布依据不对应两层正式文件")
        for audit in (raw, silver):
            fact = known_records[audit.path]
            known_records[audit.path] = (audit, fact[1], fact[2])
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
        return date_result(True, False, entry)
    if imported:
        if source.source_empty:
            targets = (
                raw_stk_factor_pro_path(lake_root, day.isoformat()),
                silver_stock_factor_pro_path(lake_root, day.isoformat()),
            )
            if any(path.exists() for path in targets):
                raise ValueError("bootstrap空源目标已出现文件但缺合法补数依据")
            for path in targets:
                known_records[path] = (None, None, None)
        else:
            for intent, complete in original:
                if (
                    factor_known_file_sha(
                        complete.audit.path, known_records=known_records
                    )
                    != complete.actual_file_sha256
                ):
                    raise ValueError("bootstrap正式文件改变或缺失且无合法补数凭据")
                fact = known_records[complete.audit.path]
                known_records[complete.audit.path] = (
                    complete.audit,
                    fact[1],
                    fact[2],
                )
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
        return date_result(True, False, None)
    return date_result(False, True, None)


def _bootstrap_space_check(
    connection,
    *,
    lake_root,
    staging_root,
    approval,
    counts,
    classified,
    progress=None,
    known_records,
):
    """One operation's remaining disk needs; no extra data reads or durable state."""
    temp_directory = Path(
        connection.execute("SELECT current_setting('temp_directory')").fetchone()[0]
    )
    pending_sources = {
        month.month_start: sum(
            counts[d]
            for d, item in classified.items()
            for source in (item["source_complete"],)
            if source is None and month.month_start <= d < month.month_end_exclusive
        )
        for month in approval.month_limits
    }
    remaining_layers, working = {}, {}
    working_by_month = {}
    unpublished_layers = set()
    remaining_dates = set(counts)
    for day, item in classified.items():
        valid = item["current_files_verified"]
        rows = (
            item["raw_audit"].row_count
            if item["current_publication"] is not None
            else counts[day]
        )
        working[day] = (rows, rows)
        working_by_month.setdefault((day.year, day.month), []).append(day)
        if valid or rows == 0:
            continue
        for layer in ("raw", "silver"):
            intent = known_records[
                R.operation_path(
                    staging_root, approval, f"publication/{day}/{layer}/intent.json"
                )
            ][0]
            complete = item[f"{layer}_complete"]
            if complete is not None:
                if (
                    factor_known_file_sha(
                        complete.audit.path, known_records=known_records
                    )
                    != complete.actual_file_sha256
                ):
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
                        and factor_known_file_sha(target, known_records=known_records)
                        == intent.expected_file_sha256
                    ) or (
                        candidate.is_file()
                        and factor_known_file_sha(
                            candidate, known_records=known_records
                        )
                        == intent.candidate.file_sha256
                    )
                if not satisfied:
                    remaining_layers[day, layer] = rows
    remaining_layer_total_rows = sum(remaining_layers.values())
    remaining_layer_file_count = len(remaining_layers)
    observed = {
        "row": C.STK_FACTOR_PRO_ESTIMATED_ROW_BYTES,
        "file": C.STK_FACTOR_PRO_ESTIMATED_FILE_OVERHEAD_BYTES,
        "record": C.STK_FACTOR_PRO_ESTIMATED_RECORD_BYTES,
    }
    record_sizes = {}
    record_group_sizes = {}
    known_record_bytes = 0
    active_month = None
    summary_phase = False

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
            remaining_layer_file_count, \
            summary_phase
        if month_start is not None:
            active_month = month_start
        observation = None
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
                observation = (
                    "record_group",
                    None,
                    C.STK_FACTOR_PRO_ESTIMATED_RECORD_BYTES,
                    record_group_sizes[trade_date],
                )
            elif rows:
                observed["row"] = max(
                    observed["row"],
                    (max(0, size - observed["file"]) + rows - 1) // rows,
                )
                observation = (
                    "data_file",
                    rows,
                    C.STK_FACTOR_PRO_ESTIMATED_ROW_BYTES * rows
                    + C.STK_FACTOR_PRO_ESTIMATED_FILE_OVERHEAD_BYTES,
                    size,
                )
        if event == "final_statistics":
            summary_phase = True
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
        if summary_phase:
            work_rows = (0, 0)
        elif trade_date is not None:
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
            pending_source_rows_by_month=()
            if summary_phase
            else tuple(pending_sources.values()),
            remaining_layer_rows=(),
            remaining_layer_totals=(0, 0)
            if summary_phase
            else (
                remaining_layer_total_rows,
                remaining_layer_file_count,
            ),
            work_rows=(0, 0) if summary_phase else work_rows,
            pending_fetch_rows=0
            if summary_phase
            else min(
                C.STK_FACTOR_PRO_BOOTSTRAP_FETCH_ROWS,
                pending_sources.get(
                    active_month, max(pending_sources.values(), default=0)
                ),
            ),
            remaining_date_count=0 if summary_phase else len(remaining_dates),
            statistics_only=summary_phase
            or (not any(pending_sources.values()) and not unpublished_layers),
            observed_row_bytes=observed["row"],
            observed_file_overhead=observed["file"],
            observed_record_bytes=observed["record"],
        )
        if not summary_phase:
            estimate = replace(
                estimate,
                record_bytes=max(0, estimate.record_bytes - known_record_bytes),
            )
        if progress is not None:
            details = None
            if observation is not None:
                kind, observed_rows, initial_bytes, actual_bytes = observation
                details = {
                    "stage": stage,
                    "trade_date": None
                    if trade_date is None
                    else trade_date.isoformat(),
                    "kind": kind,
                    "rows": observed_rows,
                    "initial_estimate_bytes": initial_bytes,
                    "actual_bytes": actual_bytes,
                    "difference_bytes": actual_bytes - initial_bytes,
                }
            progress.observe_space(
                stage=stage, estimate=estimate, observed=observed, observation=details
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
    known_records,
):
    """Internal dependency-injected orchestration; never an operator path override."""
    _roots(lake_root, staging_root)
    require_stk_factor_pro_no_other_active_runs(instance)
    root = stk_factor_pro_bootstrap_operation_root(staging_root, operation_id)
    approval = R.read_json(
        root / "approval.json",
        C.StkFactorProBootstrapApproval,
        known_records=known_records,
    )
    if approval is None or approval.operation_id != operation_id:
        raise ValueError("bootstrap缺本operation管理员批准记录")
    source_inputs = S._approved_inputs(
        connection,
        staging_root=staging_root,
        approval=approval,
        known_records=known_records,
    )
    counts = source_inputs[0]
    preflight_context = {"fixed_done": False, "checked_windows": {}}
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
            known_records=known_records,
        )
        for day in days
    }
    approval_digest = known_records[root / "approval.json"][1]
    summary_path = root / "coverage/summary.json"
    previous_summary = R.read_json(
        summary_path,
        C.StkFactorProBootstrapCoverageSummary,
        known_records=known_records,
    )
    previous_summary_digest = known_records[summary_path][1]
    if previous_summary is not None and (
        previous_summary.operation_id,
        previous_summary.approval_digest,
        previous_summary.start_trade_date,
        previous_summary.end_trade_date,
    ) != (
        approval.operation_id,
        approval_digest,
        approval.start_trade_date,
        approval.end_trade_date,
    ):
        raise ValueError("bootstrap已有summary不属于本次批准范围")
    summary_state = new_stk_factor_pro_bootstrap_coverage_totals(natural_dates=days)
    basis_inputs = {"files": {}, "months": {}, "active_month": None}

    def refresh_date(day, is_open):
        refresh_stk_factor_pro_bootstrap_date_contribution(
            trade_date=day,
            entry=classified[day],
            totals=summary_state,
            is_open=is_open,
            approved_rows=counts[day],
        )

    for day in days:
        refresh_date(day, None)
    progress.configure(
        total_dates=len(days),
        reused_source_rows=sum(
            source.actual_rows
            for item in classified.values()
            for source in (item["source_complete"],)
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
        progress=progress,
        known_records=known_records,
    )
    check_space("读取前核磁盘空间", path=root)
    checked = False

    def before_publish():
        nonlocal checked
        require_stk_factor_pro_bootstrap_source_window(approval=approval, now=_now())
        if not checked:
            require_stk_factor_pro_no_other_active_runs(instance)
            checked = True

    def save_summary():
        check_space("最终统计准备前", path=root, event="final_statistics")
        return summarize_stk_factor_pro_bootstrap_coverage(
            staging_root=staging_root,
            approval=approval,
            approval_digest=approval_digest,
            totals=summary_state,
            previous_summary=previous_summary,
            previous_summary_digest=previous_summary_digest,
            check_space=check_space,
            known_records=known_records,
        )[0]

    try:
        with R.resource_cleanup(
            lambda: release_stk_factor_pro_bootstrap_coverage_inputs(
                connection, basis_inputs=basis_inputs
            )
        ):
            _process_stk_factor_pro_bootstrap_months(
                connection,
                lake_root=lake_root,
                staging_root=staging_root,
                approval=approval,
                classified=classified,
                instance=instance,
                prod_postgres=prod_postgres,
                progress=progress,
                known_records=known_records,
                source_inputs=source_inputs,
                preflight_context=preflight_context,
                check_space=check_space,
                before_publish=before_publish,
                basis_inputs=basis_inputs,
                refresh_date=refresh_date,
            )
    except BaseException as error:
        try:
            save_summary()
        except BaseException as cleanup:  # noqa: BLE001 -- summary is failure observability and must preserve the original task error.
            error.add_note(f"bootstrap失败汇总保存同时失败：{type(cleanup).__name__}")
        raise
    return save_summary()


def _process_stk_factor_pro_bootstrap_months(
    connection,
    *,
    lake_root,
    staging_root,
    approval,
    classified,
    instance,
    prod_postgres,
    progress,
    known_records,
    source_inputs,
    preflight_context,
    check_space,
    before_publish,
    basis_inputs,
    refresh_date,
):
    root = stk_factor_pro_bootstrap_operation_root(staging_root, approval.operation_id)
    counts = source_inputs[0]
    days = tuple(classified)
    for month in approval.month_limits:
        check_space("准备本月工作前", path=root, month_start=month.month_start)
        verification = R.BootstrapFragmentVerification(
            connection,
            staging_root=staging_root,
            approval=approval,
            month=month,
            known_records=known_records,
        )
        with R.resource_cleanup(
            verification.close,
            lambda: release_stk_factor_pro_bootstrap_coverage_month(
                connection, basis_inputs=basis_inputs
            ),
        ):
            inputs = prepare_stk_factor_pro_bootstrap_coverage_month(
                connection,
                lake_root=lake_root,
                staging_root=staging_root,
                approval=approval,
                month=month,
                basis_inputs=basis_inputs,
                known_records=known_records,
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
            for day in month_days:
                is_open = (
                    True
                    if day in inputs.open_dates
                    else False
                    if day in inputs.closed_dates
                    else None
                )
                refresh_date(day, is_open)
            pending = tuple(
                d for d in month_days if classified[d]["source_complete"] is None
            )
            recover = tuple(d for d in month_days if classified[d]["needs_restore"])
            for day in inputs.closed_dates:
                source = classified[day]["source_complete"]
                valid = classified[day]["current_files_verified"]
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
                    source_inputs=source_inputs,
                    preflight_context=preflight_context,
                    known_records=known_records,
                )

            def complete_date(
                source,
                *,
                source_record_sha256,
                source_relation,
                inputs=inputs,
            ):
                day = source.trade_date
                entry = classified[day]
                entry["source_complete"] = source
                entry["source_record_sha256"] = source_record_sha256
                try:
                    value = process_stk_factor_pro_bootstrap_complete_date(
                        connection,
                        lake_root=lake_root,
                        staging_root=staging_root,
                        approval=approval,
                        source_complete=source,
                        source_record_sha256=source_record_sha256,
                        source_relation=source_relation,
                        inputs=inputs,
                        basis_inputs=basis_inputs,
                        before_publish=before_publish,
                        check_space=check_space,
                        progress=progress,
                        known_records=known_records,
                        date_results=classified,
                    )
                    S._validate_date_result(source, value)
                    progress.date_completed(
                        day=day,
                        source_rows=source.actual_rows,
                        raw=value.raw_audit,
                        silver=value.silver_audit,
                        coverage=value.coverage,
                    )
                    check_space(
                        "完整日期处理完成",
                        path=root,
                        trade_date=day,
                        rows=source.actual_rows,
                        event="date_completed",
                    )
                    return value
                finally:
                    refresh_date(
                        day,
                        True
                        if day in inputs.open_dates
                        else False
                        if day in inputs.closed_dates
                        else None,
                    )

            for day in month_days:
                item = classified[day]
                source = item["source_complete"]
                if source is None:
                    continue
                if item["current_files_verified"]:
                    if day in inputs.closed_dates:
                        continue
                    raw, silver = item["raw_audit"], item["silver_audit"]
                    try:
                        value = _complete_existing_bootstrap_coverage(
                            connection,
                            lake_root=lake_root,
                            staging_root=staging_root,
                            approval=approval,
                            inputs=inputs,
                            basis_inputs=basis_inputs,
                            entry=item,
                            date_results=classified,
                            check_space=check_space,
                            known_records=known_records,
                        )
                        progress.date_completed(
                            day=day,
                            source_rows=source.actual_rows,
                            raw=raw,
                            silver=silver,
                            coverage=value,
                        )
                        check_space(
                            "当前日期统计完成",
                            path=root,
                            trade_date=day,
                            rows=0 if raw is None else raw.row_count,
                            event="date_completed",
                        )
                    finally:
                        refresh_date(day, True if day in inputs.open_dates else None)
                else:
                    with R.resource_cleanup(
                        lambda: connection.execute(
                            f"DROP TABLE IF EXISTS {BOOTSTRAP_DAY_SOURCE}"
                        )
                    ):
                        raw_complete = item["raw_complete"]
                        if raw_complete is None:
                            relation = R.load_complete_source(
                                connection,
                                staging_root=staging_root,
                                approval=approval,
                                record=source,
                                verification=verification,
                                known_records=known_records,
                            )
                        else:
                            raw_path = raw_stk_factor_pro_path(
                                lake_root, day.isoformat()
                            )
                            if (
                                factor_known_file_sha(
                                    raw_path, known_records=known_records
                                )
                                != raw_complete.actual_file_sha256
                            ):
                                raise ValueError("bootstrap恢复Raw文件与完成记录不符")
                            connection.execute(
                                f"CREATE TEMP TABLE {BOOTSTRAP_DAY_SOURCE} AS SELECT * "
                                f"FROM {read_parquet(raw_path, hive_partitioning=False)}"
                            )
                            if (
                                factor_file_identity(raw_path)
                                != known_records[raw_path][2]
                            ):
                                raise ValueError("bootstrap恢复Raw在首次读取期间改变")
                            relation = BOOTSTRAP_DAY_SOURCE
                        complete_date(
                            source,
                            source_record_sha256=item["source_record_sha256"],
                            source_relation=relation,
                        )
            if pending:
                export_stk_factor_pro_bootstrap_month(
                    prod_postgres=prod_postgres,
                    connection=connection,
                    staging_root=staging_root,
                    approval=approval,
                    month=month,
                    selected_dates=pending,
                    source_inputs=source_inputs,
                    preflight_context=preflight_context,
                    on_complete_date=complete_date,
                    check_space=check_space,
                    verification=verification,
                    progress=progress,
                    known_records=known_records,
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
    known_records = {}
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
            known_records=known_records,
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
