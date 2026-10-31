"""First-history reconciliation and separately frozen bootstrap catchup scopes."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import aliased

from src.foundation.dao.stock_weekly_adj_delivery_dao import StockWeeklyAdjDeliveryDAO
from src.foundation.datasets.stock_weekly_adj_contracts import (
    WeeklyAdjContractError,
    digest,
)
from src.foundation.ingestion.stock_weekly_adj_planning import (
    load_daily_codes,
    parse_day,
)
from src.foundation.ingestion.stock_weekly_adj_scope import (
    build_weekly_adj_requested_units,
)
from src.foundation.models.core.stock_weekly_adj_delivery import (
    StockWeeklyAdjDelivery as Delivery,
)
from src.foundation.models.core.trade_calendar import TradeCalendar as Calendar
from src.foundation.models.core_serving.equity_adj_factor import (
    EquityAdjFactor as Factor,
)
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar as Daily
from src.foundation.models.core_serving.stk_period_bar_adj import (
    StkPeriodBarAdj as Serving,
)
from src.foundation.models.raw.raw_stk_period_bar_adj import RawStkPeriodBarAdj as Raw


def bootstrap_parent(session):
    return session.scalar(
        select(Delivery)
        .where(
            Delivery.record_kind == "batch_closed",
            Delivery.intent["bootstrap"].as_boolean().is_(True),
            Delivery.payload["bootstrap_reconciled"].as_boolean().is_(True),
            Delivery.payload["bootstrap_parent"].as_string().is_(None),
        )
        .order_by(Delivery.revision.desc())
        .limit(1)
    )


def bootstrap_factor_scope(session, policy, *, today=None, history_cutoff=None):
    """One bounded code inventory result, indexed per-code daily dates, no row export."""
    today = today or datetime.now(UTC).date()
    end = session.scalar(
        select(func.max(Daily.trade_date)).where(
            Daily.source == "tushare", Daily.trade_date <= today
        )
    )
    if end is None or not session.scalar(
        select(Calendar.is_open).where(
            Calendar.exchange == "SSE", Calendar.trade_date == end
        )
    ):
        raise WeeklyAdjContractError(
            "首次收尾缺少开市日日线依据", "weekly_adj.factor_coverage_missing"
        )
    daily = load_daily_codes(session, [end], policy)[end]
    factors = dict(
        session.execute(
            select(Factor.ts_code, Factor.adj_factor)
            .where(Factor.trade_date == end)
            .limit(policy.max_rows_per_unit + 1)
        ).all()
    )
    if len(factors) > policy.max_rows_per_unit:
        raise WeeklyAdjContractError(
            "收尾因子超过对象预算", "weekly_adj.row_budget_exceeded"
        )
    if any(factors.get(c) is None or factors[c] <= 0 for c in daily):
        raise WeeklyAdjContractError(
            "收尾日线代码缺少有效因子", "weekly_adj.factor_coverage_missing"
        )
    inventory_query = (
        select(Raw.ts_code, func.min(Raw.trade_date).label("start_date"))
        .where(Raw.freq == "week")
        .group_by(Raw.ts_code)
    )
    if history_cutoff is not None:
        # A stock first introduced by a new-week unit has no parent history.
        # Its source values are checked by that unit, not the parent target digest.
        inventory_query = inventory_query.having(
            func.min(Raw.trade_date) <= history_cutoff
        )
    inventory = inventory_query.subquery()
    last = (
        select(Daily.trade_date)
        .where(
            Daily.ts_code == inventory.c.ts_code,
            Daily.source == "tushare",
            Daily.trade_date <= end,
        )
        .order_by(Daily.trade_date.desc())
        .limit(1)
        .correlate(inventory)
        .scalar_subquery()
    )
    targets = select(
        inventory.c.ts_code, inventory.c.start_date, last.label("last_date")
    ).subquery()
    dates = (
        select(Raw.ts_code, Raw.end_date)
        .where(Raw.freq == "week")
        .distinct()
        .cte("bootstrap_basis_dates")
        .prefix_with("MATERIALIZED", dialect="postgresql")
    )
    basis = (
        select(Factor.adj_factor)
        .where(Factor.ts_code == dates.c.ts_code, Factor.trade_date == dates.c.end_date)
        .correlate(dates)
        .scalar_subquery()
    )
    pairs = (
        select(dates.c.ts_code, basis.label("basis_factor"))
        .cte("bootstrap_basis_values")
        .prefix_with("MATERIALIZED", dialect="postgresql")
    )
    target = aliased(Factor)
    known = and_(pairs.c.basis_factor > 0, target.adj_factor > 0)
    statement = (
        select(
            targets.c.ts_code,
            targets.c.start_date,
            targets.c.last_date,
            target.adj_factor,
            func.sum(
                case(
                    (and_(known, pairs.c.basis_factor != target.adj_factor), 1), else_=0
                )
            ).label("changed"),
            func.sum(case((known, 0), else_=1)).label("unverified"),
        )
        .select_from(targets)
        .join(pairs, pairs.c.ts_code == targets.c.ts_code)
        .outerjoin(
            target,
            and_(
                target.ts_code == targets.c.ts_code,
                target.trade_date == targets.c.last_date,
            ),
        )
        .group_by(
            targets.c.ts_code,
            targets.c.start_date,
            targets.c.last_date,
            target.adj_factor,
        )
        .order_by(targets.c.ts_code)
        .limit(policy.max_rows_per_unit + 1)
    )
    rows = session.execute(statement).all()
    if len(rows) > policy.max_rows_per_unit:
        raise WeeklyAdjContractError(
            "首次收尾代码库存超过预算", "weekly_adj.row_budget_exceeded"
        )
    changed = {
        code: (start, value, day) for code, start, day, value, change, _ in rows if change
    }
    unverified = [code for code, _, _, _, _, count in rows if count]
    if len(changed) > policy.max_units:
        raise WeeklyAdjContractError(
            "补刷代码超过单批单元预算", "weekly_adj.row_budget_exceeded"
        )
    return (
        changed,
        end,
        {
            "unverified_codes": len(unverified),
            "unverified_samples": unverified[:20],
            "targets_digest": digest(
                [
                    [
                        code,
                        day.isoformat() if day else None,
                        format(value, ".8f") if value is not None else None,
                    ]
                    for code, _, day, value, _, _ in rows
                ]
            ),
        },
    )


def plan_bootstrap_catchup(session, request, definition, parent, cutoff, *, today=None):
    """Second existing full-range maintain intent, with its own frozen batch/units."""
    original = StockWeeklyAdjDeliveryDAO(session).get_record(
        batch_id=parent.batch_id, record_kind="plan", unit_id="plan"
    )
    if original is None:
        raise WeeklyAdjContractError("首次收尾缺少原冻结计划")
    scope = original.payload["execution_context"]["requested_scope"]
    if (
        request.start_date > parse_day(scope["start_date"])
        or cutoff < parent.cutoff_week
    ):
        raise WeeklyAdjContractError(
            "收尾范围未覆盖原始全量范围", "weekly_adj.scope_mismatch"
        )
    changes, end, audit = bootstrap_factor_scope(
        session,
        definition.planning.weekly_adj_policy,
        today=today,
        history_cutoff=parent.cutoff_week,
    )
    units = []
    week = parent.cutoff_week + timedelta(days=7)
    while week <= cutoff:
        units.extend(
            build_weekly_adj_requested_units(
                replace(
                    request,
                    run_profile="point_incremental",
                    trade_date=week,
                    start_date=None,
                    end_date=None,
                ),
                definition,
            )
        )
        week += timedelta(days=7)
    for code, (start, target, target_date) in changes.items():
        unit = build_weekly_adj_requested_units(
            replace(
                request,
                params={**request.params, "ts_code": code},
                start_date=start,
                end_date=cutoff,
            ),
            definition,
        )[0]
        units.append(
            replace(
                unit,
                progress_context={
                    **unit.progress_context,
                    "factor_target": format(target, ".8f"),
                    "factor_target_date": target_date.isoformat(),
                },
            )
        )
    return units, end, audit


def audit_bootstrap_units(
    session, *, definition, context, units, transaction, check, progress
):
    """Persist each once-only reconciliation; no whole-history transaction."""
    from src.foundation.ingestion.stock_weekly_adj_delivery import (
        delivery_record,
        unit_scope,
    )
    from src.foundation.ingestion.stock_weekly_adj_reconciliation import reconcile_scope

    policy = definition.planning.weekly_adj_policy
    dao = StockWeeklyAdjDeliveryDAO(session)
    for ordinal, unit in enumerate(units, 1):
        check()
        identity = "audit:" + unit.unit_id
        old = dao.get_record(
            batch_id=context["execution_token"], record_kind="unit", unit_id=identity
        )
        if old is not None:
            if old.scope_digest != context[
                "scope_hash"
            ] or old.payload_digest != digest(old.payload):
                raise WeeklyAdjContractError("首次对账持久化事实不一致")
            session.expunge(old)
            session.rollback()
            continue
        session.rollback()
        progress("首次逐单元对账", ordinal - 1, len(units), unit)
        with transaction(session, policy, check) as ensure:
            receipt = dao.get_record(
                batch_id=context["execution_token"],
                record_kind="unit",
                unit_id=unit.unit_id,
            )
            if receipt is None or not receipt.intent["bootstrap"]:
                raise WeeklyAdjContractError("首次对账缺少源单元结果")
            reconcile_scope(
                session,
                {m: unit_scope(unit, m) for m in (Raw, Serving)},
                receipt.payload["summary"],
                policy,
                check,
            )
            dao.append(
                delivery_record(
                    context=context,
                    kind="unit",
                    unit_id=identity,
                    unit=unit,
                    payload={
                        "summary": {
                            "audited_unit_id": unit.unit_id,
                            "source_digest": receipt.payload_digest,
                        }
                    },
                ),
                policy,
            )
            ensure()
            session.commit()
        progress("首次逐单元对账", ordinal, len(units), unit)
        check()


def publish_bootstrap_boundary(session, *, definition, context, check):
    from src.foundation.ingestion.stock_weekly_adj_delivery import delivery_record

    policy = definition.planning.weekly_adj_policy
    dao = StockWeeklyAdjDeliveryDAO(session)
    meta = context["business_plan"]["metadata"]
    parent = dao.get_record(
        batch_id=meta["bootstrap_parent_batch"],
        record_kind="batch_closed",
        unit_id="batch_closed",
    )
    closed = dao.get_record(
        batch_id=context["execution_token"],
        record_kind="batch_closed",
        unit_id="batch_closed",
    )
    if (
        parent is None
        or closed is None
        or parent.revision != meta["bootstrap_parent_revision"]
        or not parent.payload.get("bootstrap_reconciled")
        or not closed.payload.get("bootstrap_reconciled")
    ):
        raise WeeklyAdjContractError("首次/补刷批尚未完整对账闭合")
    changes, end, audit = bootstrap_factor_scope(
        session, policy, history_cutoff=parent.cutoff_week
    )
    unavailable = []
    for code, (_, target, _) in changes.items():
        check()
        unit = next(
            (
                u
                for u in context["business_plan"]["units"]
                if u["progress"].get("factor_target")
                and u["params"].get("ts_code") == code
            ),
            None,
        )
        receipt = (
            dao.get_record(
                batch_id=context["execution_token"],
                record_kind="unit",
                unit_id=unit["unit_id"],
            )
            if unit
            else None
        )
        if receipt is None or receipt.outcome not in {
            "source_empty_preserved",
            "partial_source_preserved",
        }:
            continue
        # A proven missing source key can remain stale. Never excuse an incoming
        # row whose independent factor check should have matched the frozen target.
        retained = {
            tuple(k)
            for k in receipt.payload["summary"]["preserved_values"]["raw"]["keys"]
        }
        stale = session.execute(
            select(Raw.ts_code, Raw.trade_date)
            .join(
                Factor,
                and_(Factor.ts_code == Raw.ts_code, Factor.trade_date == Raw.end_date),
            )
            .where(
                Raw.freq == "week",
                Raw.ts_code == code,
                Factor.adj_factor > 0,
                Factor.adj_factor != target,
            )
            .limit(policy.max_rows_per_unit + 1)
        ).all()
        if len(stale) > policy.max_rows_per_unit:
            raise WeeklyAdjContractError(
                "未刷新键超过单元预算", "weekly_adj.row_budget_exceeded"
            )
        keys = {(c, day.strftime("%Y%m%d")) for c, day in stale}
        if keys and keys <= retained:
            unavailable.append(code)
        session.expunge(receipt)
    audit.update(
        source_unavailable_codes=len(unavailable),
        source_unavailable_samples=unavailable[:20],
    )
    if (
        end.isoformat() != meta["factor_scan_end"]
        or audit["targets_digest"] != meta["bootstrap_basis_audit"]["targets_digest"]
        or set(changes) - set(unavailable)
    ):
        raise WeeklyAdjContractError(
            "收尾期间因子基准再次变化，保留原批并停止B0", "weekly_adj.basis_not_updated"
        )
    rows, first, last = session.execute(
        select(func.count(), func.min(Raw.trade_date), func.max(Raw.trade_date)).where(
            Raw.freq == "week"
        )
    ).one()
    check()
    payload = {
        **closed.payload,
        "bootstrap_parent": {
            "batch_id": str(parent.batch_id),
            "revision": parent.revision,
            "payload_digest": parent.payload_digest,
        },
        "inventory": {
            "rows": rows,
            "first_date": first.isoformat() if first else None,
            "last_date": last.isoformat() if last else None,
        },
    }
    return dao.append(
        delivery_record(
            context=context,
            kind="bootstrap_closed",
            unit_id="bootstrap_closed",
            payload=payload,
            rows_received=closed.rows_received,
            rows_unique=closed.rows_unique,
            rows_written=closed.rows_written,
            rows_preserved=closed.rows_preserved,
            reason_summary={"basis_audit": audit},
        ),
        policy,
    )
