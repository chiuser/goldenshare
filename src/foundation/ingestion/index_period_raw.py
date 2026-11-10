"""Read, validate and commit one official index period at a time."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from time import monotonic, sleep

from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from src.foundation.ingestion.errors import IngestionError, StructuredError
from src.foundation.ingestion.executor import IngestionRunSummary
from src.foundation.ingestion.progress import IngestionObserver
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.foundation.ingestion.source_client import SourceFetchResult
from src.foundation.ingestion.writer import DatasetWriter


MISSING_PERIOD_CODE = "index_period_raw.source_missing"
_LOGGER = logging.getLogger(__name__)


def _resident_bytes(pid: int) -> int:
    if sys.platform == "linux":
        try:
            with open(f"/proc/{pid}/statm", encoding="ascii") as statm:
                return int(statm.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
        except FileNotFoundError:
            return 0
    result = subprocess.run(
        ["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, check=False,
    )
    return int(result.stdout.strip() or 0) * 1024


class _PeriodControl:
    def __init__(self, *, policy, unit, index, report, check_cancel):
        self.policy = policy
        self.unit = unit
        self.started_at = monotonic()
        self.write_started_at = None
        self.child_pid = None
        self.next_cancel = self.next_report = self.started_at
        self.check_cancel = check_cancel
        self.report_snapshot = report
        self.diagnostics = {
            "unit_id": unit.unit_id, "unit_index": index,
            "time": {"field": "trade_date", "point": unit.trade_date.isoformat()},
            "ts_code": unit.request_params.get("ts_code"),
            "phase": "processing_page", "page_limit": unit.page_limit,
            "completed_page_count": 0, "unit_rows_fetched": 0, "retry_count": 0,
        }

    def error(self, code, message, **details):
        return IngestionError(StructuredError(
            error_code=f"index_period_raw.{code}", error_type="execute", phase=self.diagnostics["phase"],
            message=message, retryable=False, unit_id=self.unit.unit_id, details=details,
        ))

    def set_child_pid(self, pid):
        self.child_pid = pid

    def report(self, *, force=False):
        now = monotonic()
        if force or now >= self.next_report:
            self.next_report = now + self.policy.progress_interval_seconds
            self.diagnostics["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.report_snapshot(self.diagnostics)

    def check(self, *, force_cancel=False):
        now = monotonic()
        if force_cancel or now >= self.next_cancel:
            self.next_cancel = now + self.policy.cancel_poll_seconds
            if self.check_cancel():
                raise IngestionCanceledError("指数周期线 Raw 维护已收到停止请求")
        rss = _resident_bytes(os.getpid())
        if self.child_pid is not None:
            rss += _resident_bytes(self.child_pid)
        if rss >= self.policy.memory_limit_bytes:
            raise self.error("memory_limit", "指数周期线 Raw 单期内存达到上限",
                             actual_bytes=rss, limit_bytes=self.policy.memory_limit_bytes)
        self.report()
        now = monotonic()
        self._remaining(now, self.started_at, self.policy.unit_timeout_seconds, "unit_deadline")
        if self.write_started_at is not None:
            self._remaining(now, self.write_started_at, self.policy.db_timeout_seconds, "write_deadline")

    def _remaining(self, now, started_at, limit, code):
        elapsed = now - started_at
        if elapsed >= limit:
            raise self.error(code, "指数周期线 Raw 单期执行达到时间上限",
                             actual_seconds=round(elapsed, 3), limit_seconds=limit)
        return limit - elapsed

    def source_timeout(self):
        return min(self.policy.source_timeout_seconds, self._remaining(
            monotonic(), self.started_at, self.policy.unit_timeout_seconds, "unit_deadline",
        ))

    def wait(self, seconds):
        until = monotonic() + seconds
        while (remaining := until - monotonic()) > 0:
            self.check()
            unit_remaining = self.started_at + self.policy.unit_timeout_seconds - monotonic()
            sleep(max(0, min(remaining, unit_remaining, self.policy.cancel_poll_seconds)))

    def fetching(self, page_number, offset):
        self.diagnostics.update(current_page_number=page_number, offset=offset)
        self.check(force_cancel=True)

    def check_rows(self, index):
        if index % self.unit.page_limit == 0:
            self.check(force_cancel=True)

    def before_write(self, conn, cursor, statement, parameters, context, executemany):
        self.check(force_cancel=True)
        if conn.dialect.name == "postgresql":
            now = monotonic()
            remaining = min(
                self._remaining(now, self.write_started_at, self.policy.db_timeout_seconds, "write_deadline"),
                self._remaining(now, self.started_at, self.policy.unit_timeout_seconds, "unit_deadline"),
            )
            cursor.execute(f"SET LOCAL statement_timeout = '{max(1, int(remaining * 1000))}ms'")


def _fetch_period(executor, definition, unit, control, count_rows):
    rows = []
    seen_keys = set()
    fields = set(definition.source.source_fields)
    expected_code = unit.request_params.get("ts_code")
    for page in executor.source_client.iter_pages(definition=definition, unit=unit, control=control):
        count_rows(len(page.rows_raw))
        control.diagnostics.update(
            completed_page_count=page.page_number,
            unit_rows_fetched=len(rows) + len(page.rows_raw),
            retry_count=control.diagnostics["retry_count"] + page.retry_count,
            observed_short_page=page.is_short_page,
        )
        control.check(force_cancel=True)
        if len(page.rows_raw) > unit.page_limit:
            raise control.error("invalid_page", "Tushare 返回行数超过单页请求大小",
                                page=page.page_number, actual_rows=len(page.rows_raw), limit=unit.page_limit)
        # A code occurs only once in a valid period. Catch a repeated/overlapping
        # page before attempting the next request.
        for row in page.rows_raw:
            code = row.get("ts_code")
            source_date = row.get("trade_date")
            if isinstance(code, str) and isinstance(source_date, str):
                key = (code, source_date)
                if key in seen_keys:
                    raise control.error("invalid_page", "Tushare 分页重复返回同一指数和日期",
                                        page=page.page_number, ts_code=code, actual_date=source_date)
                seen_keys.add(key)
        rows.extend(page.rows_raw)

    control.diagnostics.update(phase="reconciling")
    control.report(force=True)
    for index, row in enumerate(rows):
        control.check_rows(index)
        missing = fields.difference(row)
        if missing:
            raise control.error("source_payload_invalid", "Tushare 返回缺少指数行情字段",
                                ts_code=row.get("ts_code"), missing_fields=sorted(missing))
        if not isinstance(row["ts_code"], str) or not row["ts_code"].strip():
            raise control.error("source_payload_invalid", "Tushare 返回的指数代码为空或类型错误",
                                actual_ts_code=repr(row["ts_code"])[:64])
        if expected_code and row["ts_code"] != expected_code:
            raise control.error("source_payload_invalid", "Tushare 返回的指数不在本次请求范围",
                                expected_ts_code=expected_code, actual_ts_code=row["ts_code"])
    return rows


def _commit_readback(bind, definition, batch, unit):
    """Resolve a lost COMMIT acknowledgement by comparing this unit's business values."""
    with Session(bind=bind) as probe:
        if bind.dialect.name == "postgresql":
            probe.execute(text("SELECT set_config('statement_timeout', :timeout, true)"),
                          {"timeout": f"{definition.planning.index_period_raw_policy.db_timeout_seconds}s"})
        table = getattr(DatasetWriter(probe).dao, definition.storage.raw_dao_name).model.__table__
        columns = [table.c[name] for name in (*definition.source.source_fields, "api_name")]
        query = select(*columns).where(table.c.trade_date == unit.trade_date)
        if code := unit.request_params.get("ts_code"):
            query = query.where(table.c.ts_code == code)
        actual = {row["ts_code"]: row for row in probe.execute(query).mappings()}
        for row in batch.rows_normalized:
            stored = actual.get(row["ts_code"])
            if stored is None:
                return False
            for column in columns:
                expected = row.get(column.name)
                if isinstance(expected, Decimal):
                    expected = expected.quantize(Decimal(1).scaleb(-column.type.scale), rounding=ROUND_HALF_UP)
                if stored[column.name] != expected:
                    return False
    return True


def _publish_period(bind, definition, batch, unit, control):
    control.diagnostics.update(phase="publishing", unit_rows_normalized_before_dedupe=len(batch.rows_normalized))
    control.report(force=True)
    control.write_started_at = monotonic()
    with Session(bind=bind) as business:
        connection = business.connection()
        event.listen(connection, "before_cursor_execute", control.before_write)
        try:
            result = DatasetWriter(business).write(definition=definition, batch=batch, plan_unit=unit)
            control.check(force_cancel=True)
        except IngestionError as exc:
            cause = exc.__cause__
            if isinstance(cause, IngestionCanceledError):
                raise cause from None
            if isinstance(cause, IngestionError):
                raise cause from None
            if isinstance(cause, DBAPIError) and getattr(cause.orig, "sqlstate", None) == "57014":
                now = monotonic()
                unit_deadline = control.started_at + control.policy.unit_timeout_seconds
                write_deadline = control.write_started_at + control.policy.db_timeout_seconds
                unit_limited = unit_deadline <= write_deadline
                started = control.started_at if unit_limited else control.write_started_at
                limit = control.policy.unit_timeout_seconds if unit_limited else control.policy.db_timeout_seconds
                code = "unit_deadline" if unit_limited else "write_deadline"
                raise control.error(code, "指数周期线 Raw 写入触发 SQL 时间上限",
                                    actual_seconds=round(now - started, 3), limit_seconds=limit) from cause
            control.check()
            raise
        finally:
            event.remove(connection, "before_cursor_execute", control.before_write)
        try:
            business.commit()
        except DBAPIError as exc:
            if not exc.connection_invalidated:
                raise
            business.rollback()
            try:
                confirmed = _commit_readback(bind, definition, batch, unit)
            except DBAPIError:
                confirmed = False
            if not confirmed:
                raise control.error("commit_unconfirmed", "指数周期线 Raw 提交结果无法确认，请按原范围重试") from exc
        return result.rows_written


def run_index_period_raw(executor, *, request, definition, units, cancel_checker, progress_reporter):
    policy = definition.planning.index_period_raw_policy
    observer = IngestionObserver(progress_reporter)
    unit_done = unit_failed = rows_fetched = rows_committed = rows_rejected = 0
    missing_periods = []
    total = len(units)

    def diagnostics(active=None):
        return {
            "index_period_raw": {
                "unit_done": unit_done, "unit_failed": unit_failed,
                "missing_period_count": len(missing_periods),
            },
            "runtime": {"paged_unit": {"active": dict(active, unit_total=total) if active else None}},
        }

    def report(active):
        if not active:
            message = f"{definition.display_name} Raw 已处理 {unit_done + unit_failed}/{total} 期"
            current = {}
        else:
            stage = {"processing_page": "分页取数", "reconciling": "整期校验", "publishing": "写入 Raw",
                     "failed": "执行失败", "canceled": "已取消"}[active["phase"]]
            message = f'{definition.display_name} {active["time"]["point"]} {stage}（{unit_done + unit_failed}/{total} 期）'
            current = {"trade_date": active["time"]["point"], "ts_code": active["ts_code"]}
        try:
            observer.report_progress(
                run_id=request.run_id, dataset_key=request.dataset_key, unit_total=total,
                unit_done=unit_done, unit_failed=unit_failed, rows_fetched=rows_fetched,
                rows_written=rows_committed, rows_committed=rows_committed, rows_rejected=rows_rejected,
                ingestion_diagnostics=diagnostics(active), current_object=current, message=message,
            )
        except Exception:
            _LOGGER.warning("Failed to report index period Raw progress", exc_info=True)

    def execution_progress(active=None):
        return {
            "rows_fetched": rows_fetched, "rows_saved": rows_committed, "rows_rejected": rows_rejected,
            "unit_done": unit_done, "unit_failed": unit_failed, "unit_total": total,
            "ingestion_diagnostics": diagnostics(active),
        }

    def count_rows(count):
        nonlocal rows_fetched
        rows_fetched += count

    def canceled():
        return cancel_checker is not None and request.run_id is not None and cancel_checker(request.run_id)

    def run_period(unit, control):
        nonlocal rows_rejected
        rows = _fetch_period(executor, definition, unit, control, count_rows)
        if not rows:
            return None
        retries = control.diagnostics["retry_count"]
        fetched = SourceFetchResult(
            unit_id=unit.unit_id, request_count=control.diagnostics["completed_page_count"] + retries,
            retry_count=retries, latency_ms=int((monotonic() - control.started_at) * 1000), rows_raw=rows,
        )
        batch = executor.normalizer.normalize(
            definition=definition, expected_unit_date=unit.trade_date,
            check_rows=control.check_rows, fetch_result=fetched,
        )
        rows_rejected += batch.rows_rejected
        control.check(force_cancel=True)
        for index, row in enumerate(batch.rows_normalized):
            control.check_rows(index)
            row["api_name"] = definition.source.api_name
        return _publish_period(executor.session.get_bind(), definition, batch, unit, control)

    for index, unit in enumerate(units, 1):
        control = _PeriodControl(policy=policy, unit=unit, index=index, report=report, check_cancel=canceled)
        scope = {
            "dataset_key": definition.dataset_key, "trade_date": unit.trade_date.isoformat(),
            "ts_code": unit.request_params.get("ts_code"),
        }
        try:
            control.check(force_cancel=True)
            written = run_period(unit, control)
            if written is None:
                unit_failed += 1
                missing_periods.append(scope)
            else:
                rows_committed += written
                unit_done += 1
            report(None)
            if canceled():
                raise IngestionCanceledError("指数周期线 Raw 维护已收到停止请求")
        except IngestionCanceledError as exc:
            control.diagnostics.update(phase="canceled")
            control.report(force=True)
            exc.index_period_raw_progress = execution_progress(control.diagnostics)
            raise
        except Exception as exc:
            stage = control.diagnostics["phase"]
            unit_failed += 1
            control.diagnostics.update(phase="failed")
            control.report(force=True)
            error = exc.structured_error if isinstance(exc, IngestionError) else StructuredError(
                error_code="write_failed", error_type="write", phase="writer", message=str(exc),
                retryable=False, unit_id=unit.unit_id,
            )
            details = {**scope, "stage": stage, **error.details}
            if missing_periods:
                details["missing_periods"] = missing_periods
            failure = IngestionError(replace(error, details=details))
            failure.index_period_raw_progress = execution_progress(control.diagnostics)
            raise failure from exc

    summary_diagnostics = diagnostics()
    summary_diagnostics["index_period_raw"]["missing_periods"] = missing_periods
    return IngestionRunSummary(
        dataset_key=request.dataset_key, run_profile=request.run_profile,
        unit_total=total, unit_done=unit_done, unit_failed=unit_failed, rows_fetched=rows_fetched,
        rows_written=rows_committed, rows_committed=rows_committed, rows_rejected=rows_rejected,
        rows_deduplicated=0, ingestion_diagnostics=summary_diagnostics, rejected_reason_counts={},
        rejected_reason_samples={}, result_date=executor._resolve_result_date(request),
        message=f"{definition.display_name} Raw 共 {total} 期，写入 {unit_done} 期，源缺 {len(missing_periods)} 期",
        error_counts={MISSING_PERIOD_CODE: len(missing_periods)} if missing_periods else {},
    )
