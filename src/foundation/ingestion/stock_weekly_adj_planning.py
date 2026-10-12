"""Read-only business scope resolution for the adjusted weekly publisher.

No Ops status or stock pool is a source fact. Plans carry compact scopes, never rows.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import case, exists, func, select
from sqlalchemy.orm import aliased

from src.foundation.datasets.stock_weekly_adj_contracts import (
    WeeklyAdjContractError,
    canonical_json,
    digest,
    latest_completed_calendar_week,
)
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot
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
from src.foundation.models.raw.raw_stk_period_bar_adj import RawStkPeriodBarAdj as Raw


def fail(message, code="weekly_adj.factor_coverage_missing"):
    raise WeeklyAdjContractError(message, code)


def parse_day(value):
    if type(value) is date:
        return value
    text = str(value).replace("-", "")
    return date(int(text[:4]), int(text[4:6]), int(text[6:8]))


def load_week_open_days(session, cutoff, *, previous=False):
    start = cutoff - timedelta(days=4)
    # SSE is the existing equity trade calendar convention. Require closed days too.
    rows = session.execute(
        select(Calendar.trade_date, Calendar.is_open)
        .where(
            Calendar.exchange == "SSE",
            Calendar.trade_date >= start,
            Calendar.trade_date <= cutoff,
        )
        .order_by(Calendar.trade_date)
    ).all()
    if [r.trade_date for r in rows] != [start + timedelta(days=n) for n in range(5)]:
        fail(f"{start} 至 {cutoff} 交易日历不完整")
    days = [r.trade_date for r in rows if r.is_open]
    if previous and days:
        prior = session.scalar(
            select(func.max(Calendar.trade_date)).where(
                Calendar.exchange == "SSE",
                Calendar.is_open.is_(True),
                Calendar.trade_date < days[0],
            )
        )
        if prior is None:
            fail(f"{days[0]} 缺少前一开市日")
        days.insert(0, prior)
    return days


def load_daily_codes(session, days, policy):
    if not days:
        return {}
    result = {d: set() for d in days}
    rows = session.execute(
        select(Daily.trade_date, Daily.ts_code)
        .where(Daily.trade_date.in_(days), Daily.source == "tushare")
        .order_by(Daily.trade_date, Daily.ts_code)
        .limit(policy.max_rows_per_unit * len(days) + 1)
    ).all()
    if len(rows) > policy.max_rows_per_unit * len(days):
        fail("日线上游代码集合超过预算", "weekly_adj.row_budget_exceeded")
    for day, code in rows:
        result[day].add(code)
    missing = [d for d, codes in result.items() if not codes]
    if missing:
        fail(f"开市日没有 Tushare 日线：{missing}")
    return result


def load_changed_codes(session, cutoff, policy):
    days = load_week_open_days(session, cutoff, previous=True)
    if not days:
        return {}, None, None, 0
    daily = load_daily_codes(session, days, policy)
    rows = session.execute(
        select(Factor.trade_date, Factor.ts_code, Factor.adj_factor)
        .where(Factor.trade_date.in_(days))
        .limit(policy.max_rows_per_unit * len(days) + 1)
    ).all()
    if len(rows) > policy.max_rows_per_unit * len(days):
        fail("因子集合超过预算", "weekly_adj.row_budget_exceeded")
    factors = {(d, code): value for d, code, value in rows}
    for day in days:
        missing = daily[day] - {code for d, code in factors if d == day}
        if missing:
            fail(f"{day} 日线股票缺少复权因子：{sorted(missing)[:20]}")
    changed, first = set(), set()
    candidates = {code for d, code in factors if d in days[1:]}
    if len(candidates) > policy.max_rows_per_unit:
        fail("因子对象并集超过预算", "weekly_adj.row_budget_exceeded")
    # Only ambiguous first appearances need a historical daily lookup. The common
    # complete-factor path never scans daily history for the whole market.
    ambiguous = {
        code
        for prev, day in zip(days, days[1:])
        for d, code in factors
        if d == day and (prev, code) not in factors
    }
    existed = (
        set(
            session.scalars(
                select(Daily.ts_code)
                .where(
                    Daily.ts_code.in_(ambiguous),
                    Daily.source == "tushare",
                    Daily.trade_date < days[0],
                )
                .group_by(Daily.ts_code)
            )
        )
        if ambiguous
        else set()
    )
    for prev, day in zip(days, days[1:]):
        for code in {code for d, code in factors if d == day}:
            current = factors[(day, code)]
            if current is None or current <= 0:
                fail(f"{day}/{code} 因子无效")
            before = factors.get((prev, code))
            if before is None:
                if code in existed or code in daily[prev]:
                    fail(f"{code} 有历史行情，但缺少 {prev} 相邻因子")
                first.add(code)
            elif before <= 0:
                fail(f"{prev}/{code} 因子无效")
            elif before != current:
                changed.add(code)
        existed.update(daily[prev])
    if len(changed) + 1 > policy.max_units:
        fail("因子变化股票超过单批单元预算", "weekly_adj.row_budget_exceeded")
    earliest = (
        dict(
            session.execute(
                select(Raw.ts_code, func.min(Raw.trade_date))
                .where(Raw.freq == "week", Raw.ts_code.in_(changed))
                .group_by(Raw.ts_code)
            ).all()
        )
        if changed
        else {}
    )
    missing_targets = [code for code in earliest if (days[-1], code) not in factors]
    if missing_targets:
        fail(f"变化股票缺少周末目标因子：{missing_targets[:20]}")
    return (
        {
            code: (earliest[code], factors[(days[-1], code)])
            for code in sorted(earliest)
        },
        days[1],
        days[-1],
        len(first),
    )


def latest_frontier(session):
    return session.scalar(
        select(Delivery)
        .where(
            (Delivery.record_kind == "bootstrap_closed")
            | (
                (Delivery.record_kind == "batch_closed")
                & (Delivery.intent["mode"].as_string() == "scheduled_week")
            )
        )
        .order_by(Delivery.revision.desc())
        .limit(1)
    )


def oldest_unclosed_plan(session):
    closed = aliased(Delivery)
    return session.scalar(
        select(Delivery)
        .where(
            Delivery.record_kind == "plan",
            ~exists(
                select(closed.revision).where(
                    closed.batch_id == Delivery.batch_id,
                    closed.record_kind
                    == case(
                        (
                            Delivery.payload["metadata"]["bootstrap_parent_batch"]
                            .as_string()
                            .is_not(None),
                            "bootstrap_closed",
                        ),
                        else_="batch_closed",
                    ),
                )
            ),
        )
        .order_by(Delivery.revision)
        .limit(1)
    )


def serialize_unit(unit):
    return {
        "unit_id": unit.unit_id,
        "trade_date": unit.trade_date.isoformat() if unit.trade_date else None,
        "params": unit.request_params,
        "progress": unit.progress_context,
    }


def restore_units(payload, definition):
    units = payload["units"]
    policy = definition.planning.weekly_adj_policy
    if not isinstance(units, list) or len(units) > policy.max_units:
        fail("冻结计划单元无效", "weekly_adj.delivery_contract_mismatch")
    return tuple(
        PlanUnitSnapshot(
            unit_id=u["unit_id"],
            dataset_key=definition.dataset_key,
            source_key="tushare",
            trade_date=parse_day(u["trade_date"]) if u["trade_date"] else None,
            request_params=dict(u["params"]),
            progress_context=dict(u["progress"]),
            pagination_policy="offset_limit",
            page_limit=6000,
            max_source_rows_per_unit=policy.max_rows_per_unit,
        )
        for u in units
    )


def resolve_weekly_adj_units(session, request, definition, *, now=None):
    """Called by DatasetActionResolver; reads only, including recovery/preview."""
    context = request.execution_context
    policy = definition.planning.weekly_adj_policy
    requested_units = build_weekly_adj_requested_units(request, definition)
    old = session.scalar(
        select(Delivery)
        .where(
            Delivery.batch_id == UUID(context["execution_token"]),
            Delivery.record_kind == "plan",
        )
        .limit(1)
    )
    pending = oldest_unclosed_plan(session)
    if old is None and pending is not None:
        if context["intent"] != "scheduled_week":
            fail(f"先续跑未完成批次 {pending.batch_id}", "weekly_adj.writer_busy")
        old = pending
    if old is not None:
        original = old.payload["execution_context"]
        if original["contract_digest"] != context["contract_digest"]:
            fail(
                "未完成批次与当前 Definition/预算不一致",
                "weekly_adj.delivery_contract_mismatch",
            )
        if (
            context["intent"] != "scheduled_week"
            and original["scope_hash"] != context["scope_hash"]
        ):
            fail("恢复意图范围不一致", "weekly_adj.scope_mismatch")
        restored = {**original, "business_plan": old.payload}
        scope = original["requested_scope"]
        request = replace(
            request,
            run_profile=scope["run_profile"],
            params=scope["params"],
            trade_date=parse_day(scope["trade_date"]) if scope["trade_date"] else None,
            start_date=parse_day(scope["start_date"]) if scope["start_date"] else None,
            end_date=parse_day(scope["end_date"]) if scope["end_date"] else None,
        )
        return replace(request, execution_context=restored), restore_units(
            old.payload, definition
        )

    cutoff_limit = latest_completed_calendar_week(now or datetime.now(UTC))
    if not requested_units:
        fail("所选范围没有完整周", "weekly_adj.scope_mismatch")
    max_anchor = max(
        parse_day(u.request_params.get("trade_date") or u.request_params["end_date"])
        for u in requested_units
    )
    if max_anchor > cutoff_limit:
        fail("不能捕获尚未结束的周", "weekly_adj.scope_mismatch")
    minimum = session.scalar(select(func.min(Raw.trade_date)).where(Raw.freq == "week"))
    if minimum is None:
        fail("Prod 周线库存为空，无法确定已有历史起点", "weekly_adj.scope_mismatch")
    frontier = latest_frontier(session)
    bootstrap_exists = (
        session.scalar(
            select(Delivery.revision)
            .where(Delivery.record_kind == "bootstrap_closed")
            .limit(1)
        )
        is not None
    )
    metadata = {
        "cutoff_week": max_anchor.isoformat(),
        "bootstrap": False,
        "frontier_revision": frontier.revision if frontier else 0,
        "factor_scan_start": None,
        "factor_scan_end": None,
        "first_seen_codes": 0,
    }
    units = list(requested_units)
    if context["intent"] == "scheduled_week":
        if not bootstrap_exists or frontier is None:
            fail(
                "首次全量刷新及一次完整对账尚未闭合，不能自动更新",
                "weekly_adj.source_not_ready",
            )
        candidate = frontier.cutoff_week + timedelta(days=7)
        if candidate > max_anchor:
            units = []
            metadata["cutoff_week"] = frontier.cutoff_week.isoformat()
        else:
            metadata["cutoff_week"] = candidate.isoformat()
            point = replace(request, trade_date=candidate)
            units = list(build_weekly_adj_requested_units(point, definition))
            changes, begin, end, first = load_changed_codes(session, candidate, policy)
            metadata.update(
                factor_scan_start=begin.isoformat() if begin else None,
                factor_scan_end=end.isoformat() if end else None,
                first_seen_codes=first,
            )
            for code, (start, target) in changes.items():
                historical = replace(
                    request,
                    run_profile="range_rebuild",
                    trade_date=None,
                    start_date=start,
                    end_date=candidate,
                    params={**request.params, "ts_code": code},
                )
                unit = build_weekly_adj_requested_units(historical, definition)[0]
                units.append(
                    replace(
                        unit,
                        progress_context={
                            **unit.progress_context,
                            "factor_target": format(target, ".8f"),
                        },
                    )
                )
    elif context["intent"] == "historical_refresh" and not bootstrap_exists:
        # A subset remains a replayable manual revision, never a false bootstrap.
        metadata["bootstrap"] = (
            request.start_date <= minimum and max_anchor == cutoff_limit
        )
        if metadata["bootstrap"]:
            from src.foundation.ingestion.stock_weekly_adj_bootstrap import (
                bootstrap_parent,
                plan_bootstrap_catchup,
            )

            parent = bootstrap_parent(session)
            if parent is not None:
                units, scan_end, audit = plan_bootstrap_catchup(
                    session,
                    request,
                    definition,
                    parent,
                    max_anchor,
                    today=(now or datetime.now(UTC)).date(),
                )
                metadata.update(
                    bootstrap_parent_batch=str(parent.batch_id),
                    bootstrap_parent_revision=parent.revision,
                    factor_scan_end=scan_end.isoformat(),
                    bootstrap_basis_audit=audit,
                )

    # Whole-range preview stays bounded: one grouped inventory query, not one
    # daily/history query for each of ~876 weeks. Exact weekly upstream checks
    # run immediately before each capture and are never saved as row payloads.
    historical_market = (
        request.run_profile == "range_rebuild"
        and not request.params.get("ts_code")
        and context["intent"] != "scheduled_week"
        and not metadata.get("bootstrap_parent_batch")
    )
    inventory_counts = (
        dict(
            session.execute(
                select(Raw.trade_date, func.count())
                .where(Raw.freq == "week")
                .group_by(Raw.trade_date)
            ).all()
        )
        if historical_market
        else {}
    )
    current_days = (
        load_week_open_days(session, cutoff_limit) if historical_market else []
    )
    current_codes = (
        load_daily_codes(session, current_days, policy) if historical_market else {}
    )
    market_bound = max(
        max(inventory_counts.values(), default=0),
        len(set.union(*current_codes.values())) if current_codes else 0,
    )
    estimated_bytes = 0
    for i, unit in enumerate(units):
        strict_point = bool(unit.trade_date) and (
            context["intent"] == "scheduled_week"
            or unit.trade_date == cutoff_limit
            or bool(metadata.get("bootstrap_parent_batch"))
        )
        if unit.trade_date and historical_market:
            expected_count = market_bound
            progress = dict(unit.progress_context)
            if strict_point:
                codes = set.union(*current_codes.values()) if current_codes else set()
                progress.update(
                    expected_codes_digest=digest(sorted(codes)),
                    expected_codes_count=len(codes),
                    no_trading_week=not current_days,
                )
        elif unit.trade_date and strict_point:
            days = load_week_open_days(session, unit.trade_date)
            codes_by_day = load_daily_codes(session, days, policy)
            codes = set.union(*codes_by_day.values()) if codes_by_day else set()
            if unit.request_params.get("ts_code"):
                codes &= {unit.request_params["ts_code"]}
            expected_count = len(codes)
            progress = {
                **unit.progress_context,
                "expected_codes_digest": digest(sorted(codes)),
                "expected_codes_count": expected_count,
                "no_trading_week": not days,
            }
        elif unit.trade_date:
            expected_count = 1 if unit.request_params.get("ts_code") else market_bound
            if not expected_count:
                expected_count = session.scalar(
                    select(func.count())
                    .select_from(Raw)
                    .where(Raw.freq == "week", Raw.trade_date == unit.trade_date)
                )
            progress = dict(unit.progress_context)
        else:
            start, end = (
                parse_day(unit.request_params["start_date"]),
                parse_day(unit.request_params["end_date"]),
            )
            expected_count = (end - start).days // 7 + 1
            progress = dict(unit.progress_context)
        if unit.trade_date:
            progress["require_complete_source"] = strict_point
        # 1KiB per canonical 21-field row is conservative for the defined precisions.
        estimate = expected_count * 1024
        if (
            expected_count > policy.max_rows_per_unit
            or estimate > policy.max_payload_bytes
        ):
            fail("预计单元行数或载荷超过预算", "weekly_adj.row_budget_exceeded")
        estimated_bytes += 4096 if metadata["bootstrap"] else estimate
        units[i] = replace(unit, progress_context=progress)
    if (
        len(units) > policy.max_units
        or estimated_bytes > policy.max_batch_payload_bytes
    ):
        fail("预计整批单元或载荷超过预算", "weekly_adj.row_budget_exceeded")
    metadata["estimated_payload_bytes"] = estimated_bytes
    if metadata["bootstrap"] and not metadata.get("bootstrap_parent_batch"):
        basis_days = load_week_open_days(session, cutoff_limit)
        metadata["factor_scan_end"] = basis_days[-1].isoformat() if basis_days else None
    original = {
        **context,
        "requested_scope": {
            "run_profile": request.run_profile,
            "trade_date": request.trade_date.isoformat()
            if request.trade_date
            else None,
            "start_date": request.start_date.isoformat()
            if request.start_date
            else None,
            "end_date": request.end_date.isoformat() if request.end_date else None,
            "params": {
                k: v.isoformat() if type(v) is date else v
                for k, v in request.params.items()
            },
        },
    }
    payload = {
        "execution_context": original,
        "metadata": metadata,
        "units": [serialize_unit(u) for u in units],
    }
    if len(canonical_json(payload).encode()) > policy.max_plan_bytes:
        fail("冻结业务计划超过字节预算", "weekly_adj.row_budget_exceeded")
    return replace(
        request, execution_context={**original, "business_plan": payload}
    ), tuple(units)


def restore_scheduled_request(session, request):
    """A queued automatic continuation retains the durable batch's original intent."""
    from src.foundation.ingestion.execution_plan import DatasetTimeInput

    context = request.execution_context
    if not context or not context.get("requested_scope"):
        return request
    stored = session.scalar(
        select(Delivery)
        .where(
            Delivery.batch_id == UUID(context["execution_token"]),
            Delivery.record_kind == "plan",
        )
        .limit(1)
    )
    if stored is None:
        return request
    if stored.payload["execution_context"] != {
        k: v for k, v in context.items() if k != "business_plan"
    }:
        fail(
            "自动续跑冻结意图与业务计划不一致", "weekly_adj.delivery_contract_mismatch"
        )
    original = context["requested_scope"]
    point = original["run_profile"] == "point_incremental"
    time_input = DatasetTimeInput(
        mode="point" if point else "range",
        trade_date=parse_day(original["trade_date"])
        if original["trade_date"]
        else None,
        start_date=parse_day(original["start_date"])
        if original["start_date"]
        else None,
        end_date=parse_day(original["end_date"]) if original["end_date"] else None,
    )
    return replace(
        request,
        time_input=time_input,
        filters={
            k: v
            for k, v in original["params"].items()
            if k not in {"trade_date", "start_date", "end_date"}
        },
    )
