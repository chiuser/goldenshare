from __future__ import annotations

import time
from typing import Callable


def run_ingestion_snapshot(
    *,
    session_local,
    build_maintain_service_fn,
    attach_progress_fn: Callable[..., None],
    prepare_kwargs_fn: Callable[..., dict[str, object]],
    snapshot_service_cls,
    resources: list[str],
    source_key: str | None,
    ts_code: str | None,
    list_status: str | None,
    classify: str | None,
    index_code: str | None,
    con_code: str | None,
    exchange: str | None,
    exchange_id: str | None,
    ths_type: str | None,
    idx_type: str | None,
    market: str | None,
    hot_type: str | None,
    is_new: str | None,
    tag: str | None,
    limit_type: str | None,
    echo_fn: Callable[[str], None],
) -> None:
    with session_local() as session:
        snapshot_service = snapshot_service_cls()
        for resource in resources:
            service = build_maintain_service_fn(resource, session)
            attach_progress_fn(service, resource=resource)
            kwargs = {
                "source_key": source_key,
                "ts_code": ts_code,
                "list_status": list_status,
                "classify": classify,
                "index_code": index_code,
                "con_code": con_code,
                "exchange": exchange,
                "exchange_id": exchange_id,
                "type": ths_type,
                "idx_type": idx_type,
                "market": market,
                "hot_type": hot_type,
                "is_new": is_new,
                "tag": tag,
                "limit_type": limit_type,
            }
            echo_fn(f"[{resource}] snapshot start")
            started_at = time.perf_counter()
            result = service.maintain(default_time_mode="none", **prepare_kwargs_fn(service, kwargs))
            snapshot_service.refresh_resources(session, [resource])
            elapsed_seconds = max(time.perf_counter() - started_at, 0.0)
            echo_fn(
                f"[{resource}] snapshot done "
                f"fetched={result.rows_fetched} written={result.rows_written} "
                f"elapsed={elapsed_seconds:.1f}s"
            )


def run_weekly_adj_plan_correction(
    *,
    session_local,
    task_run_id,
    output=None,
    apply=False,
    approved_plan=None,
    expected_digest=None,
    approval_ref=None,
    echo_fn=print,
):
    """Operator entrypoint. Default transaction is read-only, no TaskRun is created."""
    from contextlib import contextmanager
    from dataclasses import replace
    from datetime import UTC, datetime, timedelta
    import json
    import os
    from pathlib import Path
    from tempfile import NamedTemporaryFile
    from types import SimpleNamespace
    from sqlalchemy import event, select, text

    from src.foundation.datasets.registry import get_dataset_definition
    from src.foundation.datasets.stock_weekly_adj_contracts import (
        WeeklyAdjContractError,
        canonical_json,
        canonical_source_rows,
        digest,
        validate_correction_plan,
    )
    from src.foundation.ingestion.executor import IngestionExecutor
    from src.foundation.ingestion.request_builders import (
        _stk_period_bar_adj_week_params,
    )
    from src.foundation.ingestion.stock_weekly_adj_execution import (
        WeeklyControl,
        capture_unit,
    )
    from src.foundation.ingestion.stock_weekly_adj_planning import restore_units
    from src.foundation.ingestion.stock_weekly_adj_plan_correction import (
        apply_correction_plan,
        build_correction_plan,
        fail,
        plan_record,
        targets_for_plan,
    )
    from src.ops.models.ops.task_run import TaskRun
    from src.ops.models.ops.schedule import OpsSchedule

    if type(task_run_id) is not int or task_run_id < 1:
        fail("必须指定有效来源任务ID")
    if apply:
        if output is not None or not all(
            (approved_plan, expected_digest, approval_ref)
        ):
            fail("APPLY必须提供批准清单、摘要和批准引用，不接受output")
    elif output is None or any((approved_plan, expected_digest, approval_ref)):
        fail("只读审核必须提供output；写入参数只能与显式apply一起使用")
    definition = get_dataset_definition("stk_period_bar_adj_week")
    policy = definition.planning.weekly_adj_policy
    deadline = time.monotonic() + 30
    last_tick = 0.0

    def check():
        if time.monotonic() >= deadline:
            raise WeeklyAdjContractError(
                "更正审核超过30秒，未生成可执行清单",
                "weekly_adj.business_deadline_exceeded",
            )

    def tick(*_):
        nonlocal last_tick
        check()
        if time.monotonic() - last_tick >= 5:
            echo_fn("正在核对原计划、已提交结果及本股源样本")
            last_tick = time.monotonic()

    @contextmanager
    def audit_session():
        with session_local() as session:
            connection = session.connection()
            pg = connection.dialect.name == "postgresql"
            if pg:
                session.execute(text("SET TRANSACTION READ ONLY"))
                session.execute(text("SET LOCAL lock_timeout = '2s'"))

            def before_sql(conn, cursor, statement, parameters, context, many):
                check()
                if pg:
                    remaining = max(1, int((deadline - time.monotonic()) * 1000))
                    cursor.execute(f"SET LOCAL statement_timeout = '{remaining}ms'")

            event.listen(connection, "before_cursor_execute", before_sql)
            try:
                yield session
            finally:
                event.remove(connection, "before_cursor_execute", before_sql)
                session.rollback()

    def collect_evidence(session, unit, cutoff):
        rows, requests = [], []
        executor = IngestionExecutor(session)
        for day in (cutoff - timedelta(days=7), cutoff):
            check()
            request = SimpleNamespace(
                params={"ts_code": unit.request_params["ts_code"]},
                run_profile="point_incremental",
                trade_date=day,
            )
            params = _stk_period_bar_adj_week_params(request, day, {})
            sample = replace(unit, trade_date=day, request_params=params)
            control = WeeklyControl(check, tick, check)
            batch = capture_unit(executor, definition, sample, control)
            rows.extend(
                canonical_source_rows(
                    [
                        {n: r[n] for n in definition.source.source_fields}
                        for r in batch.rows_normalized
                    ],
                    policy,
                )
            )
            requests.append(
                dict(
                    api_name=definition.source.api_name,
                    params={**params, "limit": sample.page_limit, "offset": 0},
                    fields=list(definition.source.source_fields),
                )
            )
        return dict(
            observed_at=datetime.now(UTC).isoformat(), requests=requests, rows=rows
        )

    approved = None
    if apply:
        path = Path(approved_plan)
        if path.stat().st_size > policy.max_plan_bytes:
            fail("批准清单超过1MiB")
        approved = json.loads(path.read_text())
        validate_correction_plan(approved, policy)
        if (
            digest(approved) != expected_digest
            or approved.get("source_task_run_id") != task_run_id
        ):
            fail("批准清单摘要或来源任务不同")

    with audit_session() as session:
        source = session.get(TaskRun, task_run_id)
        if (
            source is None
            or source.task_type != "dataset_action"
            or source.action != "maintain"
            or source.resource_key != definition.dataset_key
            or source.status not in {"failed", "canceled", "partial_success"}
        ):
            fail("来源必须是已停止的同数据集维护任务")
        context = (source.request_payload_json or {}).get("execution_context", {})
        if not isinstance(context, dict) or not context.get("execution_token"):
            fail("来源任务没有冻结批次标识")
        original = plan_record(session, context["execution_token"], policy)
        if any(
            context.get(k) != original.payload["execution_context"].get(k)
            for k in ("scope_hash", "contract_digest", "intent_digest")
        ):
            fail("来源任务没有绑定相同冻结计划")
        units = restore_units(original.payload, definition)
        engine = session.get_bind()
        if apply:
            if approved["batch_id"] != str(original.batch_id):
                fail("批准清单不是来源任务的业务批次")
            if source.schedule_id is not None:
                schedule = session.get(OpsSchedule, source.schedule_id)
                if schedule is None or schedule.status == "active":
                    fail("正式更正前须暂停本数据集原排程")
            active = session.scalar(
                select(TaskRun.id)
                .where(
                    TaskRun.resource_key == definition.dataset_key,
                    TaskRun.status.in_(("queued", "running", "canceling")),
                )
                .limit(1)
            )
            if active is not None:
                fail("同数据集仍有排队或在途任务，先按既有流程停止")
            # Repeated APPLY does not request source or require an open batch.
            from src.foundation.dao.stock_weekly_adj_delivery_dao import (
                StockWeeklyAdjDeliveryDAO,
            )

            existing = StockWeeklyAdjDeliveryDAO(session).get_record(
                batch_id=approved["batch_id"],
                record_kind="plan_correction",
                unit_id="plan_correction",
            )
            if existing is None:
                c = approved["changes"][0]
                unit = next(u for u in units if u.unit_id == c["unit_id"])
                latest = collect_evidence(session, unit, original.cutoff_week)
                if (
                    latest["rows"] != approved["source_evidence"]["rows"]
                    or latest["requests"] != approved["source_evidence"]["requests"]
                ):
                    fail("批准后源小样本变化，需重新审核")
        else:
            checks = targets_for_plan(session, original.payload, check=check)
            differences = [
                c for c in checks if c["old_factor_target"] != c["new_factor_target"]
            ]
            if len(differences) != 1:
                fail("本次只允许一个已审计的因子差异")
            unit = next(u for u in units if u.unit_id == differences[0]["unit_id"])
            source_evidence = collect_evidence(session, unit, original.cutoff_week)
            approved = build_correction_plan(
                session,
                definition,
                batch_id=original.batch_id,
                source_task_run_id=task_run_id,
                source_evidence=source_evidence,
                base_units=units,
                check=check,
            )
        check()

    if apply:
        # No network or Ops writes inside the publisher lock/business transaction.
        revision = apply_correction_plan(
            engine,
            definition,
            approved,
            expected_digest=expected_digest,
            approval_ref=approval_ref,
        )
        echo_fn(f"更正记录revision={revision}；未下载历史行情或创建续跑任务")
        return revision
    encoded = canonical_json(approved)
    destination = Path(output)
    temporary = None
    try:
        check()
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=destination.name + ".",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        check()
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    echo_fn(
        f"只读审核清单已保存：{destination}；digest={digest(approved)}；未修改数据库"
    )
    return approved
