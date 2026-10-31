"""Serial weekly publishing, bounded units and observation-independent recovery."""

import logging
import time
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from src.foundation.dao.stock_weekly_adj_delivery_dao import StockWeeklyAdjDeliveryDAO
from src.foundation.datasets.stock_weekly_adj_contracts import (
    WeeklyAdjContractError,
    canonical_json_size,
    canonical_source_rows,
    digest,
    weekly_definition_issues,
)
from src.foundation.ingestion.errors import IngestionWriteError, StructuredError
from src.foundation.ingestion.progress import ProgressSnapshot
from src.foundation.ingestion.run_errors import IngestionCanceledError
from src.foundation.ingestion.source_client import SourceFetchResult
from src.foundation.ingestion.stock_weekly_adj_delivery import (
    delivery_record,
    publish_closed_batch,
)
from src.foundation.ingestion.stock_weekly_adj_planning import (
    latest_frontier,
    load_week_open_days,
    oldest_unclosed_plan,
    parse_day,
    restore_units,
)
from src.foundation.ingestion.writer import DatasetWriter

WEEKLY_ADJ_PUBLISH_LOCK = int.from_bytes(
    bytes.fromhex(digest(("stk_period_bar_adj_week", "publisher/v1")))[:8],
    "big",
    signed=True,
)


@contextmanager
def publisher_lock(engine, policy):
    if engine.dialect.name != "postgresql":
        raise WeeklyAdjContractError("正式周线发布锁只支持 PostgreSQL")
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as lock:
        lock.execute(
            text("SELECT set_config('statement_timeout', :timeout, false)"),
            {"timeout": f"{policy.db_statement_timeout_seconds}s"},
        )
        acquired = False
        try:
            acquired = bool(
                lock.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"),
                    {"key": WEEKLY_ADJ_PUBLISH_LOCK},
                )
            )
            if not acquired:
                raise WeeklyAdjContractError(
                    "已有复权周线发布者，请恢复原批或稍后重试", "weekly_adj.writer_busy"
                )
            yield
        finally:
            if acquired:
                lock.execute(
                    text("SELECT pg_advisory_unlock(:key)"),
                    {"key": WEEKLY_ADJ_PUBLISH_LOCK},
                )
            lock.execute(text("RESET statement_timeout"))


@contextmanager
def bounded_unit_transaction(session, policy, check):
    """Cumulative transaction deadline; SQL statements do not renew the unit clock."""
    check()
    connection = session.connection()
    deadline = time.monotonic() + policy.db_statement_timeout_seconds
    pg = connection.dialect.name == "postgresql"
    if pg:
        session.execute(
            text("SELECT set_config('lock_timeout', :value, true)"),
            {"value": f"{policy.lock_timeout_seconds}s"},
        )

    def ensure():
        check()
        remaining = int((deadline - time.monotonic()) * 1000)
        if remaining < 1:
            raise WeeklyAdjContractError(
                "本单元业务事务超过期限，当前单元未提交",
                "weekly_adj.business_deadline_exceeded",
            )
        return remaining

    def before_sql(conn, cursor, statement, parameters, context, executemany):
        remaining = ensure()
        if pg:
            cursor.execute(f"SET LOCAL statement_timeout = '{remaining}ms'")

    event.listen(connection, "before_cursor_execute", before_sql)
    try:
        yield ensure
    finally:
        event.remove(connection, "before_cursor_execute", before_sql)


class WeeklyControl:
    def __init__(self, check, emit, poll):
        self.check, self.emit, self.poll = check, emit, poll
        self.page_number = self.offset = 0

    def fetching(self, page_number, offset):
        self.page_number, self.offset = page_number, offset
        self.emit("下载源数据", True)

    def tick(self):
        self.emit("下载源数据", False)


def capture_unit(executor, definition, unit, control):
    policy = definition.planning.weekly_adj_policy
    raw_rows, count = [], 0
    page = None
    for page in executor.source_client.iter_weekly_adj_pages(
        definition=definition, unit=unit, control=control
    ):
        control.check()
        count += len(page.rows_raw)
        raw_rows.extend(page.rows_raw)
        # Enforce the payload/precision/key budget while pages arrive.
        canonical_source_rows(raw_rows, policy)
        control.check()
    canonical = canonical_source_rows(raw_rows, policy)
    # Decimal pages are no longer needed once canonical source validation succeeds.
    raw_rows.clear()
    page = None
    # Normalize canonical source values only; annotation/system fields never define keys.
    fetch = SourceFetchResult(
        unit_id=unit.unit_id,
        request_count=control.page_number,
        retry_count=0,
        latency_ms=0,
        rows_raw=canonical,
    )
    batch = executor.normalizer.normalize(definition=definition, fetch_result=fetch)
    if batch.rows_rejected or len(batch.rows_normalized) != len(canonical):
        raise WeeklyAdjContractError(
            "周线标准化发生拒绝行，当前单元未发布", "weekly_adj.source_payload_invalid"
        )
    batch.rows_deduplicated = count - len(canonical)
    control.check()
    return batch


def run_weekly_adj(
    executor, *, request, definition, units, cancel_checker, progress_reporter
):
    from src.foundation.ingestion.executor import IngestionRunSummary

    policy = definition.planning.weekly_adj_policy
    context = request.execution_context or {}
    payload = context.get("business_plan")
    try:
        if (
            weekly_definition_issues(definition)
            or not isinstance(payload, dict)
            or tuple(units) != restore_units(payload, definition, session=executor.session)
        ):
            raise IngestionWriteError(
                StructuredError(
                    error_code="weekly_adj.delivery_contract_mismatch",
                    error_type="write",
                    phase="weekly_adj",
                    message="周线执行必须使用 resolver 冻结的完整计划",
                    retryable=False,
                )
            )
    except WeeklyAdjContractError as exc:
        raise IngestionWriteError(StructuredError(error_code=exc.code, error_type="write",
            phase="weekly_adj", message=str(exc), retryable=False)) from exc
    closeout = bool(payload["metadata"].get("bootstrap_parent_batch"))
    engine = executor.session.get_bind()
    totals, done, last_emit, current = Counter(), 0, 0.0, {}
    diagnostic = {}
    control = None
    last_cancel = 0.0

    def check(force=False):
        nonlocal last_cancel
        now = time.monotonic()
        if force or now - last_cancel >= policy.cancel_poll_seconds:
            last_cancel = now
            if (
                cancel_checker is not None
                and request.run_id is not None
                and cancel_checker(request.run_id)
            ):
                raise IngestionCanceledError(
                    "复权周线已收到停止请求；已提交单元保留，可恢复原批"
                )

    def emit(stage, force=True):
        nonlocal last_emit, diagnostic
        if (
            not force
            and time.monotonic() - last_emit < policy.progress_interval_seconds
        ):
            return
        last_emit = time.monotonic()
        current.update(stage=stage, updated_at=datetime.now(UTC).isoformat())
        if control:
            current.update(page_number=control.page_number, offset=control.offset)
        runtime = {
            **current,
            "unit_done": done,
            "unit_total": len(units),
            "percent": done * 100 / len(units) if units else 100,
            "batch_id": context["execution_token"],
            "counters": dict(totals),
            "eta": "unavailable",
        }
        diagnostic = {"runtime": {"weekly_adj": runtime}}
        snapshot = ProgressSnapshot(
            run_id=request.run_id,
            dataset_key=definition.dataset_key,
            unit_total=len(units),
            unit_done=done,
            unit_failed=0,
            rows_fetched=totals["received"],
            rows_written=totals["written"],
            rows_committed=totals["written"],
            rows_deduplicated=totals["deduplicated"],
            ingestion_diagnostics=diagnostic,
            current_object={
                "time": {
                    "field": "trade_date",
                    "point": current.get("trade_date"),
                    "start": current.get("start_date"),
                    "end": current.get("end_date"),
                },
                "entity": {"ts_code": current.get("ts_code")},
            },
        )
        if progress_reporter:
            try:
                progress_reporter(
                    snapshot,
                    f"复权周线：{stage}；{done}/{len(units)} 单元；"
                    f"{current.get('ts_code') or '全市场'} {current.get('trade_date') or current.get('start_date') or ''}；"
                    f"已入库 {totals['written']}，保留未刷新 {totals['preserved']}；ETA暂无法估算",
                )
            except Exception:
                logging.getLogger(__name__).warning(
                    "周线观测更新失败，业务完成记录保持", exc_info=True
                )

    # Planning may open a read transaction. Release it before source waiting.
    executor.session.rollback()
    try:
        with publisher_lock(engine, policy):
            with Session(engine, expire_on_commit=False) as business:
                if tuple(units) != restore_units(payload, definition, session=business):
                    raise WeeklyAdjContractError("取得发布锁前更正记录变化，请重新提交")
                dao = StockWeeklyAdjDeliveryDAO(business)
                check(True)
                old = dao.get_record(
                    batch_id=context["execution_token"],
                    record_kind="plan",
                    unit_id="plan",
                )
                pending = oldest_unclosed_plan(business)
                if pending is not None and pending.batch_id != UUID(
                    context["execution_token"]
                ):
                    raise WeeklyAdjContractError(
                        "冻结后出现另一个未闭合批，请先续跑它", "weekly_adj.writer_busy"
                    )
                if old is not None:
                    if old.payload != payload or old.payload_digest != digest(payload):
                        raise WeeklyAdjContractError("持久化计划与当前恢复内容不一致")
                else:
                    frontier = latest_frontier(business)
                    if (frontier.revision if frontier else 0) != payload["metadata"][
                        "frontier_revision"
                    ]:
                        raise WeeklyAdjContractError(
                            "冻结后业务周水位发生变化，请重新规划",
                            "weekly_adj.source_not_ready",
                        )
                    if payload["metadata"]["bootstrap"]:
                        from src.foundation.ingestion.stock_weekly_adj_bootstrap import (
                            bootstrap_parent,
                        )

                        parent = bootstrap_parent(business)
                        expected_parent = payload["metadata"].get(
                            "bootstrap_parent_revision"
                        )
                        if (parent.revision if parent else None) != expected_parent:
                            raise WeeklyAdjContractError(
                                "冻结后首次收尾阶段发生变化，请重新规划",
                                "weekly_adj.source_not_ready",
                            )
                business.rollback()
                if (units or closeout) and old is None:
                    with bounded_unit_transaction(
                        business, policy, lambda: check(True)
                    ) as ensure:
                        dao.append(
                            delivery_record(
                                context=context,
                                kind="plan",
                                unit_id="plan",
                                payload=payload,
                            ),
                            policy,
                        )
                        ensure()
                        business.commit()
                writer = DatasetWriter(business)
                # Restore ALL committed counters before the first visible activity.
                for unit in units:
                    check(True)
                    record = dao.get_record(
                        batch_id=context["execution_token"],
                        record_kind="unit",
                        unit_id=unit.unit_id,
                    )
                    if record:
                        if record.scope_digest != context[
                            "scope_hash"
                        ] or record.payload_digest != digest(record.payload):
                            raise WeeklyAdjContractError("已提交单元范围或载荷不一致")
                        done += 1
                        totals.update(
                            received=record.rows_received,
                            written=record.rows_written,
                            preserved=record.rows_preserved,
                            deduplicated=record.rows_received - record.rows_unique,
                            payload_bytes=canonical_json_size(record.payload),
                        )
                        business.expunge(record)
                business.rollback()
                emit("恢复已提交进度")
                for ordinal, unit in enumerate(units, 1):
                    check(True)
                    current = {**unit.progress_context, "unit_index": ordinal}
                    control = WeeklyControl(lambda: check(True), emit, check)
                    record = dao.get_record(
                        batch_id=context["execution_token"],
                        record_kind="unit",
                        unit_id=unit.unit_id,
                    )
                    business.rollback()
                    if record:
                        continue
                    emit("下载新周" if unit.trade_date else "刷新股票历史")
                    no_trading = unit.trade_date and not load_week_open_days(
                        business, unit.trade_date
                    )
                    business.rollback()
                    if no_trading:
                        from src.foundation.ingestion.normalizer import NormalizedBatch

                        batch = NormalizedBatch(
                            unit_id=unit.unit_id,
                            rows_normalized=[],
                            rows_rejected=0,
                            rejected_reasons={},
                        )
                    else:
                        batch = capture_unit(executor, definition, unit, control)
                    check(True)
                    emit("校验并提交单元")
                    with bounded_unit_transaction(
                        business, policy, lambda: check(True)
                    ) as ensure:
                        result = writer.write(
                            definition=definition,
                            batch=batch,
                            plan_unit=unit,
                            delivery_context=context,
                            cancel_check=lambda: check(True),
                        )
                        facts = result.persistence_diagnostics["weekly_adj"]
                        if (
                            totals["payload_bytes"] + facts["payload_bytes"]
                            > policy.max_batch_payload_bytes
                        ):
                            raise WeeklyAdjContractError(
                                "实际整批载荷超过预算，当前单元未提交",
                                "weekly_adj.row_budget_exceeded",
                            )
                        ensure()
                        business.commit()
                    # Only an acknowledged business commit increments completion.
                    done += 1
                    totals.update(
                        received=len(batch.rows_normalized) + batch.rows_deduplicated,
                        written=result.rows_written,
                        preserved=facts["rows_preserved"],
                        deduplicated=batch.rows_deduplicated,
                        payload_bytes=facts["payload_bytes"],
                    )
                    emit("单元已提交")
                    del batch, result
                    check(True)
                if units or closeout:
                    check(True)
                    emit("闭合交付批次")
                    closed = dao.get_record(
                        batch_id=context["execution_token"],
                        record_kind="batch_closed",
                        unit_id="batch_closed",
                    )
                    business.rollback()
                    if closed is None:
                        if payload["metadata"]["bootstrap"]:
                            from src.foundation.ingestion.stock_weekly_adj_bootstrap import (
                                audit_bootstrap_units,
                            )

                            def audit_progress(stage, ordinal, total, unit):
                                nonlocal current
                                current = {
                                    **unit.progress_context,
                                    "audit_done": ordinal,
                                    "audit_total": total,
                                    "audit_percent": ordinal * 100 / total,
                                }
                                emit(
                                    f"{stage} {ordinal}/{total}（{ordinal * 100 / total:.1f}%）"
                                )

                            audit_bootstrap_units(
                                business,
                                definition=definition,
                                context=context,
                                units=units,
                                transaction=bounded_unit_transaction,
                                check=lambda: check(True),
                                progress=audit_progress,
                            )
                        with bounded_unit_transaction(
                            business, policy, lambda: check(True)
                        ) as ensure:
                            publish_closed_batch(
                                business,
                                definition=definition,
                                units=units,
                                context=context,
                                check=lambda: check(True),
                            )
                            ensure()
                            business.commit()
                    if closeout:
                        boundary = dao.get_record(
                            batch_id=context["execution_token"],
                            record_kind="bootstrap_closed",
                            unit_id="bootstrap_closed",
                        )
                        business.rollback()
                        if boundary is None:
                            from src.foundation.ingestion.stock_weekly_adj_bootstrap import (
                                publish_bootstrap_boundary,
                            )

                            emit("核验补刷基准并生成B0")
                            with bounded_unit_transaction(
                                business, policy, lambda: check(True)
                            ) as ensure:
                                publish_bootstrap_boundary(
                                    business,
                                    definition=definition,
                                    context=context,
                                    check=lambda: check(True),
                                )
                                ensure()
                                business.commit()
                emit("本批已完成" if units else "已完成周没有新增欠账")
    except BaseException as exc:
        emit("已取消" if isinstance(exc, IngestionCanceledError) else "本批未闭合")
        if isinstance(exc, WeeklyAdjContractError):
            raise IngestionWriteError(
                StructuredError(
                    error_code=exc.code,
                    error_type="write",
                    phase="weekly_adj",
                    message=str(exc),
                    retryable=exc.code
                    in {
                        "weekly_adj.source_not_ready",
                        "weekly_adj.writer_busy",
                        "weekly_adj.basis_not_updated",
                    },
                )
            ) from exc
        raise
    return IngestionRunSummary(
        dataset_key=definition.dataset_key,
        run_profile=request.run_profile,
        unit_total=len(units),
        unit_done=done,
        unit_failed=0,
        rows_fetched=totals["received"],
        rows_written=totals["written"],
        rows_committed=totals["written"],
        rows_rejected=0,
        rows_deduplicated=totals["deduplicated"],
        ingestion_diagnostics=diagnostic,
        rejected_reason_counts={},
        rejected_reason_samples={},
        result_date=parse_day(payload["metadata"]["cutoff_week"]),
        message="复权周线本批已完成；历史原键保留",
        error_counts={},
    )
