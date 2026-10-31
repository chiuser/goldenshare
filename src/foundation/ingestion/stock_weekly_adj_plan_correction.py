"""One immutable, approved factor correction per weekly batch; never writes Ops."""

from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from src.foundation.dao.stock_weekly_adj_delivery_dao import StockWeeklyAdjDeliveryDAO
from src.foundation.datasets.stock_weekly_adj_contracts import (
    WeeklyAdjContractError,
    canonical_json_size,
    digest,
    validate_correction_plan,
    validate_correction_payload,
)
from src.foundation.models.core.stock_weekly_adj_delivery import (
    StockWeeklyAdjDelivery as Delivery,
)
from .stock_weekly_adj_basis import load_weekly_factor_targets

KIND = "plan_correction"


def fail(message):
    raise WeeklyAdjContractError(message, "weekly_adj.delivery_contract_mismatch")


def receipt_headers(session, batch_id, policy):
    fields = (
        Delivery.revision,
        Delivery.unit_id,
        Delivery.payload_digest,
        Delivery.rows_written,
    )
    rows = session.execute(
        select(*fields)
        .where(
            Delivery.batch_id == UUID(str(batch_id)),
            Delivery.record_kind == "unit",
        )
        .order_by(Delivery.revision)
        .limit(policy.max_units + 1)
    ).all()
    if len(rows) > policy.max_units:
        fail("已提交单元超过计划预算")
    return [
        dict(revision=r, unit_id=u, payload_digest=d, rows_written=n)
        for r, u, d, n in rows
    ]


def plan_record(session, batch_id, policy):
    try:
        batch_id = UUID(str(batch_id))
    except (ValueError, TypeError, AttributeError):
        fail("缺少有效原批次UUID")
    record = StockWeeklyAdjDeliveryDAO(session).get_record(
        batch_id=batch_id, record_kind="plan", unit_id="plan"
    )
    if record is None or record.payload_digest != digest(record.payload):
        fail("缺少原冻结计划或原计划摘要不同")
    if canonical_json_size(record.payload) > policy.max_plan_bytes:
        fail("原计划超过预算")
    return record


def plan_binding(record):
    context = record.payload["execution_context"]
    return dict(
        batch_id=str(record.batch_id),
        cutoff_week=record.cutoff_week.isoformat(),
        original_plan_revision=record.revision,
        original_plan_digest=record.payload_digest,
        scope_digest=record.scope_digest,
        contract_digest=context["contract_digest"],
        unit_ids_digest=digest([u["unit_id"] for u in record.payload["units"]]),
    )


def assert_open(session, batch_id):
    closed = session.scalar(
        select(Delivery.revision)
        .where(
            Delivery.batch_id == UUID(str(batch_id)),
            Delivery.record_kind.in_(("batch_closed", "bootstrap_closed")),
        )
        .limit(1)
    )
    if closed is not None:
        fail("原批已经闭合，不能更正")


def targets_for_plan(session, payload, *, check=lambda: None):
    units = [
        u for u in payload["units"] if u["progress"].get("factor_target") is not None
    ]
    cutoff = date.fromisoformat(payload["metadata"]["cutoff_week"])
    targets = load_weekly_factor_targets(
        session, [u["params"]["ts_code"] for u in units], cutoff, check=check
    )
    return [
        dict(
            unit_id=u["unit_id"],
            ts_code=u["params"]["ts_code"],
            old_factor_target=u["progress"]["factor_target"],
            new_factor_target=format(targets[u["params"]["ts_code"]][1], ".8f"),
            factor_target_date=targets[u["params"]["ts_code"]][0].isoformat(),
        )
        for u in units
    ]


def validate_source_evidence(session, definition, unit, change, evidence):
    """Check complete canonical two-week producer rows, using the real basis validator."""
    from .stock_weekly_adj_delivery import (
        validate_source_scope,
        validate_weekly_adj_source_basis,
    )
    from src.foundation.datasets.stock_weekly_adj_contracts import canonical_source_rows

    if not isinstance(evidence, dict) or set(evidence) != {
        "observed_at",
        "requests",
        "rows",
    }:
        fail("源小样本证据不完整")
    try:
        observed = datetime.fromisoformat(evidence["observed_at"])
        if observed.tzinfo is None:
            raise ValueError
    except (ValueError, TypeError):
        fail("源样本取得时间必须含时区")
    rows = evidence["rows"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 2:
        fail("源核验只允许同股最近两周的完整小样本")
    canonical = canonical_source_rows(rows, definition.planning.weekly_adj_policy)
    if canonical != rows:
        fail("源证据必须是完整21字段及规范化精度，不能修改源值")
    cutoff = date.fromisoformat(change["cutoff_week"])
    allowed = {
        cutoff.strftime("%Y%m%d"),
        (cutoff - timedelta(days=7)).strftime("%Y%m%d"),
    }
    if any(
        r["ts_code"] != change["ts_code"] or r["trade_date"] not in allowed
        for r in rows
    ):
        fail("源证据超出本股最近两周")
    if cutoff.strftime("%Y%m%d") not in {r["trade_date"] for r in rows}:
        fail("源证据没有本批截止周")
    requests = evidence["requests"]
    if not isinstance(requests, list) or not requests or len(requests) > 2:
        fail("缺少实际源请求证据")
    for request in requests:
        if (
            set(request) != {"api_name", "params", "fields"}
            or request["api_name"] != definition.source.api_name
            or request["fields"] != list(definition.source.source_fields)
            or set(request["params"])
            != {"ts_code", "freq", "trade_date", "limit", "offset"}
            or request["params"]["limit"] != definition.planning.page_limit
            or request["params"]["offset"] != 0
            or request["params"]["ts_code"] != change["ts_code"]
            or request["params"]["freq"] != "week"
            or request["params"]["trade_date"] not in allowed
        ):
            fail("源请求参数或完整字段证据不同")
    if {r["params"]["trade_date"] for r in requests} != {r["trade_date"] for r in rows}:
        fail("源请求与返回周不一致")
    corrected = replace(
        unit,
        progress_context={
            **unit.progress_context,
            "factor_target": change["new_factor_target"],
        },
    )
    validate_source_scope(corrected, rows)
    validate_weekly_adj_source_basis(
        session, corrected, rows, floor=cutoff, bootstrap=False
    )


def build_correction_plan(
    session,
    definition,
    *,
    batch_id,
    source_task_run_id,
    source_evidence,
    base_units,
    check=lambda: None,
):
    policy = definition.planning.weekly_adj_policy
    check()
    record = plan_record(session, batch_id, policy)
    assert_open(session, batch_id)
    if record.payload["metadata"].get("bootstrap"):
        fail("本次更正不用于bootstrap")
    if type(source_task_run_id) is not int or source_task_run_id < 1:
        fail("缺少来源任务ID")
    expected = record.payload["units"]
    serialized = [
        dict(
            unit_id=u.unit_id,
            trade_date=u.trade_date.isoformat() if u.trade_date else None,
            params=u.request_params,
            progress=u.progress_context,
        )
        for u in base_units
    ]
    if serialized != expected or len(expected) > policy.max_units:
        fail("审核单位与原计划不一致")
    checks = targets_for_plan(session, record.payload, check=check)
    changes = [
        c
        for c in checks
        if Decimal(c["old_factor_target"]) != Decimal(c["new_factor_target"])
    ]
    if len(changes) != 1:
        fail("本次只允许一个已审计的因子差异，需重新审核")
    headers = receipt_headers(session, batch_id, policy)
    completed = {h["unit_id"] for h in headers}
    if any(h["unit_id"] not in {u.unit_id for u in base_units} for h in headers):
        fail("原批包含计划之外的交付结果")
    change = changes[0]
    unit = next(u for u in base_units if u.unit_id == change["unit_id"])
    if (
        unit.progress_context.get("unit_kind") != "stock_history"
        or unit.unit_id in completed
    ):
        fail("不能更正已经提交或非股票历史单元")
    validate_source_evidence(
        session,
        definition,
        unit,
        {**change, "cutoff_week": record.cutoff_week.isoformat()},
        source_evidence,
    )
    result = dict(
        correction_version=1,
        **plan_binding(record),
        source_task_run_id=source_task_run_id,
        units=deepcopy(expected),
        committed_units=headers,
        target_checks=checks,
        changes=changes,
        source_evidence=deepcopy(source_evidence),
    )
    validate_correction_plan(result, policy)
    check()
    return result


def corrected_units(session, payload, definition, base_units):
    policy = definition.planning.weekly_adj_policy
    batch_id = payload["execution_context"]["execution_token"]
    dao = StockWeeklyAdjDeliveryDAO(session)
    correction = dao.get_record(batch_id=batch_id, record_kind=KIND, unit_id=KIND)
    if correction is None:
        return tuple(base_units)
    validate_correction_payload(correction.payload, policy)
    if correction.payload_digest != digest(correction.payload):
        fail("更正记录摘要不同")
    approved = correction.payload["approved_plan"]
    original = plan_record(session, batch_id, policy)
    if original.payload != payload or any(
        approved[k] != v for k, v in plan_binding(original).items()
    ):
        fail("更正记录没有绑定同一原冻结计划")
    if (
        approved["units"] != payload["units"]
        or correction.scope_digest != original.scope_digest
        or correction.intent != original.intent
        or correction.cutoff_week != original.cutoff_week
    ):
        fail("更正记录改变了原单元或范围")
    headers = {h["unit_id"]: h for h in receipt_headers(session, batch_id, policy)}
    if set(headers) - {u.unit_id for u in base_units}:
        fail("原批出现计划之外的交付单元")
    if any(headers.get(h["unit_id"]) != h for h in approved["committed_units"]):
        fail("更正前已提交的单元发生变化")
    changed = {c["unit_id"]: c for c in approved["changes"]}
    result = []
    for unit in base_units:
        c = changed.get(unit.unit_id)
        if c:
            if (
                unit.progress_context.get("unit_kind") != "stock_history"
                or unit.request_params.get("ts_code") != c["ts_code"]
                or unit.progress_context.get("factor_target") != c["old_factor_target"]
                or unit.unit_id in {h["unit_id"] for h in approved["committed_units"]}
            ):
                fail("更正目标不是原计划中尚未提交的同股历史单元")
            unit = replace(
                unit,
                progress_context={
                    **unit.progress_context,
                    "factor_target": c["new_factor_target"],
                    "factor_target_date": c["factor_target_date"],
                    "plan_correction_revision": correction.revision,
                    "plan_correction_digest": correction.payload_digest,
                },
            )
            receipt = dao.get_record(
                batch_id=batch_id, record_kind="unit", unit_id=unit.unit_id
            )
            if receipt is not None:
                validate_corrected_receipt(unit, receipt)
        result.append(unit)
    return tuple(result)


def validate_corrected_receipt(unit, receipt):
    progress = unit.progress_context
    if progress.get("factor_target") is not None and receipt.factor_target != Decimal(
        progress["factor_target"]
    ):
        fail("交付因子与冻结或更正后的目标不同")
    if "plan_correction_revision" in progress:
        expected = {
            k: progress[k]
            for k in ("plan_correction_revision", "plan_correction_digest")
        }
        if any(receipt.reason_summary.get(k) != v for k, v in expected.items()):
            fail("交付单元未引用相同更正记录")


def apply_correction_plan(
    engine, definition, approved, *, expected_digest, approval_ref, check=lambda: None
):
    from sqlalchemy.orm import Session
    from .stock_weekly_adj_execution import publisher_lock, bounded_unit_transaction
    from .stock_weekly_adj_delivery import delivery_record
    from .stock_weekly_adj_planning import restore_units

    policy = definition.planning.weekly_adj_policy
    validate_correction_plan(approved, policy)
    if digest(approved) != expected_digest:
        fail("批准清单摘要不一致")
    payload = dict(
        correction_version=1,
        approved_plan=approved,
        approved_plan_digest=expected_digest,
        approval_ref=approval_ref,
    )
    validate_correction_payload(payload, policy)
    with (
        publisher_lock(engine, policy),
        Session(engine, expire_on_commit=False) as session,
    ):
        with bounded_unit_transaction(session, policy, check) as ensure:
            dao = StockWeeklyAdjDeliveryDAO(session)
            existing = dao.get_record(
                batch_id=approved["batch_id"], record_kind=KIND, unit_id=KIND
            )
            if existing is not None:
                if existing.payload != payload or existing.payload_digest != digest(
                    payload
                ):
                    fail("同一批已经有不同的批准更正")
                original = plan_record(session, approved["batch_id"], policy)
                corrected_units(
                    session,
                    original.payload,
                    definition,
                    restore_units(original.payload, definition),
                )
                return existing.revision
            original = plan_record(session, approved["batch_id"], policy)
            units = restore_units(original.payload, definition)
            current = build_correction_plan(
                session,
                definition,
                batch_id=approved["batch_id"],
                source_task_run_id=approved["source_task_run_id"],
                source_evidence=approved["source_evidence"],
                base_units=units,
                check=check,
            )
            if current != approved:
                fail("批准后计划、已提交结果或实际因子发生变化，需重新审核")
            context = {
                **original.payload["execution_context"],
                "business_plan": original.payload,
            }
            record = delivery_record(
                context=context,
                kind=KIND,
                unit_id=KIND,
                payload=payload,
                reason_summary={"source_task_run_id": approved["source_task_run_id"]},
            )
            stored = dao.append(record, policy)
            ensure()
            revision = stored.revision
            session.commit()
            check()
            return revision
