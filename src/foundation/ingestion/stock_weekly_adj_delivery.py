"""Weekly unit publication. All business effects belong to the caller's transaction."""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select, tuple_

from src.foundation.dao.stock_weekly_adj_delivery_dao import StockWeeklyAdjDeliveryDAO
from src.foundation.datasets.stock_weekly_adj_contracts import (
    SOURCE_FIELDS,
    SOURCE_ROW_BLOCK_SIZE,
    WeeklyAdjContractError,
    canonical_json_size,
    canonical_source_rows,
    digest,
    weekly_definition_issues,
)
from src.foundation.ingestion.normalizer import NormalizedBatch
from src.foundation.ingestion.stock_weekly_adj_planning import (
    load_daily_codes,
    load_week_open_days,
    parse_day,
)
from src.foundation.ingestion.stock_weekly_adj_reconciliation import (
    key,
    preservation_summary,
    reconcile_scope,
)
from src.foundation.models.core_serving.equity_adj_factor import (
    EquityAdjFactor as Factor,
)
from src.foundation.models.core_serving.stk_period_bar_adj import (
    StkPeriodBarAdj as Serving,
)
from src.foundation.models.raw.raw_stk_period_bar_adj import RawStkPeriodBarAdj as Raw


def fail(message, code="weekly_adj.scope_mismatch"):
    raise WeeklyAdjContractError(message, code)


def unit_scope(unit, model):
    filters = [model.freq == "week"]
    if unit.trade_date:
        filters.append(model.trade_date == unit.trade_date)
    else:
        filters.extend(
            (
                model.trade_date >= parse_day(unit.request_params["start_date"]),
                model.trade_date <= parse_day(unit.request_params["end_date"]),
            )
        )
    if unit.request_params.get("ts_code"):
        filters.append(model.ts_code == unit.request_params["ts_code"])
    return filters


def validate_source_scope(unit, rows):
    for row in rows:
        day = parse_day(row["trade_date"])
        if day.weekday() != 4 or row["freq"] != "week":
            fail("返回行不是周五 week 行情")
        if (
            unit.request_params.get("ts_code")
            and row["ts_code"] != unit.request_params["ts_code"]
        ):
            fail("源返回了请求范围之外的股票")
        if unit.trade_date:
            if day != unit.trade_date:
                fail("源返回了请求周之外的行情")
        elif (
            not parse_day(unit.request_params["start_date"])
            <= day
            <= parse_day(unit.request_params["end_date"])
        ):
            fail("源历史行情越界")


def _load_basis_inputs(session, candidates, required_targets, target_day):
    """Indexed last-date lookups in bounded SQL batches, never full history rows."""
    from .stock_weekly_adj_basis import load_daily_basis_dates

    dates, factors = {}, {}
    for start in range(0, len(candidates), 128):
        chunk = candidates[start:start + 128]
        lookups = []
        for row in chunk:
            code, week = row["ts_code"], parse_day(row["trade_date"])
            lookups.append((code, "week", week - timedelta(days=4), week))
            if code in required_targets:
                lookups.append((code, "target", None, target_day))
        dates.update(load_daily_basis_dates(session, lookups))
        keys = set()
        for row in chunk:
            code = row["ts_code"]
            for day in (
                dates.get((code, "week")),
                dates.get((code, "target")),
                parse_day(row["end_date"]) if row["end_date"] else None,
            ):
                if day:
                    keys.add((code, day))
        if keys:
            factors.update(
                ((code, day), value)
                for code, day, value in session.execute(
                    select(Factor.ts_code, Factor.trade_date, Factor.adj_factor).where(
                        tuple_(Factor.ts_code, Factor.trade_date).in_(sorted(keys))
                    )
                )
            )
    return dates, factors


def validate_weekly_adj_source_basis(session, unit, rows, *, floor, bootstrap):
    """Enforce the factor basis; compare sampled close prices for diagnostics only."""
    price_audit = {
        "price_compared": 0,
        "price_difference_count": 0,
        "price_max_absolute_difference": "0",
        "price_max_relative_difference": None,
        "price_difference_samples": [],
    }
    if not rows:
        return None, {"checked": 0, "optional_null_rows": 0, **price_audit}
    by_code = {}
    for row in rows:
        by_code.setdefault(row["ts_code"], []).append(row)
    for code, group in by_code.items():
        if len({r["end_date"] for r in group}) != 1:
            fail(f"{code} 的历史页混用了计算截至日期", "weekly_adj.basis_not_updated")
    nulls = sum(any(r[n] is None for n in SOURCE_FIELDS[4:]) for r in rows)
    reference_day = floor or (
        unit.trade_date
        if unit.progress_context.get("require_complete_source")
        else None
    )
    lagged = {
        code
        for code, group in by_code.items()
        if group[0]["end_date"]
        and (
            any(parse_day(r["end_date"]) < parse_day(r["trade_date"]) for r in group)
            or (reference_day and parse_day(group[0]["end_date"]) < reference_day)
        )
    }
    selected = set(sorted(by_code)[:20]) | lagged
    target = unit.progress_context.get("factor_target")
    required_targets = set(lagged)
    if target:
        required_targets.update(by_code)
        selected.update(by_code)
    candidates = [by_code[code][0] for code in sorted(selected)]
    target_day = floor or unit.trade_date or parse_day(unit.request_params["end_date"])
    dates, factors = _load_basis_inputs(
        session, candidates, required_targets, target_day
    )
    sampled, checked, lagged_verified, unverified = None, 0, 0, []
    max_absolute, max_relative = Decimal(0), None
    for row in candidates:
        code = row["ts_code"]
        basis = parse_day(row["end_date"]) if row["end_date"] else None
        last = dates.get((code, "week"))
        needed = [last, basis]
        if code in required_targets:
            needed.append(dates.get((code, "target")))
        if (
            row["close"] is None
            or row["close_qfq"] is None
            or any(
                day is None
                or factors.get((code, day)) is None
                or factors[(code, day)] <= 0
                for day in needed
            )
        ):
            unverified.append(code)
            if code in required_targets and not bootstrap:
                fail(
                    f"{code} 缺少独立日线/因子依据，无法验证本次复权价格",
                    "weekly_adj.factor_coverage_missing",
                )
            continue
        basis_factor = factors[(code, basis)]
        if code in required_targets:
            target_factor = factors[(code, dates[(code, "target")])]
            if target and target_factor != Decimal(target):
                fail(
                    f"{code} 实际目标因子与冻结计划不同，需重新审计原批",
                    "weekly_adj.basis_not_updated",
                )
            if basis_factor != target_factor:
                fail(
                    f"{code} 源基准因子与本次目标因子不同，复权价格尚未覆盖本次变化",
                    "weekly_adj.basis_not_updated",
                )
        expected = (
            Decimal(row["close"]) * factors[(code, last)] / basis_factor
        ).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        source_price = Decimal(row["close_qfq"])
        difference = source_price - expected
        absolute = abs(difference)
        relative = absolute / abs(source_price) if source_price else None
        max_absolute = max(max_absolute, absolute)
        if relative is not None:
            max_relative = (
                relative if max_relative is None else max(max_relative, relative)
            )
        if difference:
            price_audit["price_difference_count"] += 1
            if len(price_audit["price_difference_samples"]) < 20:
                price_audit["price_difference_samples"].append(
                    {
                        "ts_code": code,
                        "trade_date": row["trade_date"],
                        "actual_trade_date": last.isoformat(),
                        "source_basis_date": basis.isoformat(),
                        "trade_factor": str(factors[(code, last)]),
                        "basis_factor": str(basis_factor),
                        "source_close_qfq": str(source_price),
                        "calculated_close_qfq": str(expected),
                        "difference": str(difference),
                        "absolute_difference": str(absolute),
                        "relative_difference": str(relative)
                        if relative is not None
                        else None,
                    }
                )
        checked += 1
        lagged_verified += code in lagged
        if sampled is None:
            sampled = (basis, code, row["trade_date"])
    if sampled is None and not bootstrap:
        fail(
            "没有可独立验证的旧周 close/因子基准，本单元保持未完成",
            "weekly_adj.factor_coverage_missing",
        )
    if not bootstrap and any(
        r[n] is None
        for r in rows
        for n in ("open_qfq", "high_qfq", "low_qfq", "close_qfq", "end_date")
    ):
        fail("本次刷新缺少复权核心值或计算截至日期", "weekly_adj.source_not_ready")
    price_audit.update(
        price_compared=checked,
        price_max_absolute_difference=str(max_absolute),
        price_max_relative_difference=str(max_relative)
        if max_relative is not None
        else None,
    )
    return sampled[0] if sampled else None, {
        "checked": checked,
        "code": sampled[1] if sampled else None,
        "trade_date": sampled[2] if sampled else None,
        "optional_null_rows": nulls,
        "earlier_basis_codes": len(lagged),
        "earlier_basis_verified": lagged_verified,
        "unverified_codes": len(unverified),
        "unverified_samples": [
            {"ts_code": code, "reason": "weekly_adj.factor_coverage_missing"}
            for code in unverified[:20]
        ],
        **price_audit,
    }


def delivery_record(*, context, kind, unit_id, payload, unit=None, **counts):
    meta = context["business_plan"]["metadata"]
    intent = {
        "mode": context["intent"],
        "trigger_source": context["trigger_source"],
        "bootstrap": meta["bootstrap"],
        "intent_digest": context["intent_digest"],
    }
    return dict(
        contract_version=1,
        batch_id=context["execution_token"],
        unit_id=unit_id,
        record_kind=kind,
        intent=intent,
        unit_kind=unit.progress_context["unit_kind"] if unit else None,
        cutoff_week=parse_day(meta["cutoff_week"]),
        start_date=parse_day(unit.request_params["start_date"])
        if unit and unit.request_params.get("start_date")
        else None,
        end_date=parse_day(unit.request_params["end_date"])
        if unit and unit.request_params.get("end_date")
        else None,
        ts_code=unit.request_params.get("ts_code") if unit else None,
        factor_scan_start=parse_day(meta["factor_scan_start"])
        if meta["factor_scan_start"]
        else None,
        factor_scan_end=parse_day(meta["factor_scan_end"])
        if meta["factor_scan_end"]
        else None,
        factor_target=Decimal(unit.progress_context["factor_target"])
        if unit and unit.progress_context.get("factor_target")
        else None,
        outcome=counts.pop("outcome", "published"),
        payload=payload,
        rows_received=counts.pop("rows_received", 0),
        rows_unique=counts.pop("rows_unique", 0),
        rows_written=counts.pop("rows_written", 0),
        rows_preserved=counts.pop("rows_preserved", 0),
        basis_date=counts.pop("basis_date", None),
        payload_digest=digest(payload),
        scope_digest=context["scope_hash"],
        reason_summary=counts.pop("reason_summary", {}),
        **counts,
    )


def publish_unit(writer, *, definition, unit, batch, context, check):
    """Raw + Serving + readback + receipt, without commit or Ops calls."""
    policy = definition.planning.weekly_adj_policy
    if policy is None or weekly_definition_issues(definition) or batch.rows_rejected:
        fail("复权周线合同无效或存在拒绝行", "weekly_adj.delivery_contract_mismatch")
    check()
    incoming = canonical_source_rows(
        [{n: row[n] for n in SOURCE_FIELDS} for row in batch.rows_normalized], policy
    )
    validate_source_scope(unit, incoming)
    if unit.progress_context.get("plan_correction_revision") and not incoming:
        fail("更正目标的源历史变为空，需重新审核", "weekly_adj.source_not_ready")
    session = writer.session
    metadata = context["business_plan"]["metadata"]
    existing = set(
        session.execute(
            select(Raw.ts_code, Raw.trade_date)
            .where(*unit_scope(unit, Raw))
            .limit(policy.max_rows_per_unit + 1)
        ).all()
    )
    if len(existing) > policy.max_rows_per_unit:
        fail("原库存单元超过预算", "weekly_adj.row_budget_exceeded")
    keys = {(r["ts_code"], parse_day(r["trade_date"])) for r in incoming}
    missing = existing - keys
    no_trading = False
    if unit.trade_date:
        days = load_week_open_days(session, unit.trade_date)
        no_trading = not days
        strict = unit.progress_context["require_complete_source"]
        daily = load_daily_codes(session, days, policy) if strict else {}
        expected = set.union(*daily.values()) if daily else set()
        if unit.request_params.get("ts_code"):
            expected &= {unit.request_params["ts_code"]}
        actual = {r["ts_code"] for r in incoming}
        frozen = unit.progress_context.get("expected_codes_digest")
        if frozen and digest(sorted(expected)) != frozen:
            fail("冻结后上游日线代码集合发生变化", "weekly_adj.source_not_ready")
        if (strict and actual != expected) or (no_trading and incoming):
            fail(
                f"本周源代码不完整：缺 {sorted(expected - actual)[:20]}；额外 {sorted(actual - expected)[:20]}",
                "weekly_adj.source_not_ready",
            )
    if (
        unit.trade_date
        and strict
        and incoming
        and any(
            r[n] is None
            for r in incoming
            for n in ("open_qfq", "high_qfq", "low_qfq", "close_qfq", "end_date")
        )
    ):
        fail("本周源行缺少前复权核心值或计算截至日期", "weekly_adj.source_not_ready")
    floor = (
        parse_day(metadata["factor_scan_end"]) if metadata["factor_scan_end"] else None
    )
    basis, audit = validate_weekly_adj_source_basis(
        session, unit, incoming, floor=floor, bootstrap=metadata["bootstrap"]
    )
    preserved_values = None
    filters_by_model = {model: unit_scope(unit, model) for model in (Raw, Serving)}
    if metadata["bootstrap"]:
        preserved_values = preservation_summary(
            session, filters_by_model, {key(r) for r in incoming}, policy, check
        )
    # Normalization is the one owner of date/Decimal/change_amount conversion.
    check()
    if incoming:
        # Keep SQL compilation/coercion and readback proportional to a small block.
        # All blocks stay in the caller's one unit transaction; none commits here.
        for start in range(0, len(batch.rows_normalized), SOURCE_ROW_BLOCK_SIZE):
            check()
            writer._write_raw_and_core(
                batch=NormalizedBatch(
                    unit_id=batch.unit_id,
                    rows_normalized=batch.rows_normalized[
                        start : start + SOURCE_ROW_BLOCK_SIZE
                    ],
                    rows_rejected=0,
                    rejected_reasons={},
                ),
                raw_dao=writer.dao.raw_stk_period_bar_adj,
                core_dao=writer.dao.stk_period_bar_adj,
                raw_conflict_columns=definition.storage.raw_conflict_columns,
                conflict_columns=definition.storage.conflict_columns,
            )
            check()
        # Read only after every write, so identical duplicate keys across blocks
        # have the same final-value semantics as the previous unit-wide upsert.
        for start in range(0, len(incoming), SOURCE_ROW_BLOCK_SIZE):
            expected_rows = incoming[start : start + SOURCE_ROW_BLOCK_SIZE]
            block_keys = [
                (r["ts_code"], parse_day(r["trade_date"])) for r in expected_rows
            ]
            for model in (Raw, Serving):
                check()
                statement = select(
                    *(
                        getattr(
                            model,
                            "change_amount"
                            if model is Serving and n == "change"
                            else n,
                        ).label(n)
                        for n in SOURCE_FIELDS
                    )
                ).where(
                    model.freq == "week",
                    tuple_(model.ts_code, model.trade_date).in_(block_keys),
                )
                readback = [dict(r) for r in session.execute(statement).mappings()]
                if canonical_source_rows(readback, policy) != expected_rows:
                    fail(
                        "Raw/Serving 同事务读回键和值不一致",
                        "weekly_adj.delivery_contract_mismatch",
                    )
                del readback
                check()
        committed_rows = incoming
    else:
        committed_rows = []
    outcome = (
        "no_trading_week"
        if no_trading
        else "source_empty_preserved"
        if not incoming
        else "partial_source_preserved"
        if missing
        else "published"
    )
    payload = (
        {
            "summary": {
                "rows": len(committed_rows),
                "rows_digest": digest(committed_rows),
                "max_input_week": max(
                    (
                        parse_day(row["trade_date"]).isoformat()
                        for row in committed_rows
                    ),
                    default=None,
                ),
                "basis": audit,
                "preserved_values": preserved_values,
            }
        }
        if metadata["bootstrap"]
        else {"rows": committed_rows}
    )
    reason = {
        "counts": {outcome: len(missing)},
        "samples": [
            {
                "ts_code": c,
                "trade_date": d.strftime("%Y%m%d"),
                "reason": "weekly_adj.partial_source_preserved"
                if incoming
                else "weekly_adj.source_empty_preserved",
            }
            for c, d in sorted(missing)[:20]
        ],
    }
    reason["preserved_keys"] = [
        {"ts_code": c, "trade_date": d.strftime("%Y%m%d")} for c, d in sorted(missing)
    ]
    reason["basis_audit"] = audit
    for name in ("plan_correction_revision", "plan_correction_digest"):
        if name in unit.progress_context:
            reason[name] = unit.progress_context[name]
    if unit.progress_context.get("factor_target"):
        from .stock_weekly_adj_basis import load_weekly_factor_targets
        day, _ = load_weekly_factor_targets(session, [unit.request_params["ts_code"]],
            floor or unit.trade_date or parse_day(unit.request_params["end_date"]))[unit.request_params["ts_code"]]
        reason["factor_target_date"] = day.isoformat()
    if metadata["bootstrap"]:
        reconcile_scope(session, filters_by_model, payload["summary"], policy, check)
    check()
    return StockWeeklyAdjDeliveryDAO(session).append(
        delivery_record(
            context=context,
            kind="unit",
            unit_id=unit.unit_id,
            payload=payload,
            unit=unit,
            rows_received=len(batch.rows_normalized) + batch.rows_deduplicated,
            rows_unique=len(committed_rows),
            rows_written=len(committed_rows),
            rows_preserved=len(missing),
            basis_date=basis,
            outcome=outcome,
            reason_summary=reason,
        ),
        policy,
    )


def publish_closed_batch(session, *, definition, units, context, check):
    dao = StockWeeklyAdjDeliveryDAO(session)
    policy = definition.planning.weekly_adj_policy
    unit_ids = [u.unit_id for u in units]
    summaries, received, written, preserved, total_bytes = [], 0, 0, 0, 0
    max_input_week = None
    # Load at most one unit payload at a time, retaining only compact digests.
    for unit in units:
        check()
        receipt = dao.get_record(
            batch_id=context["execution_token"],
            record_kind="unit",
            unit_id=unit.unit_id,
        )
        if receipt is None or receipt.scope_digest != context["scope_hash"]:
            fail(
                "冻结单元缺少已提交的业务结果", "weekly_adj.delivery_contract_mismatch"
            )
        from .stock_weekly_adj_plan_correction import validate_corrected_receipt
        validate_corrected_receipt(unit, receipt)
        if receipt.payload_digest != digest(receipt.payload):
            fail("单元载荷摘要不一致", "weekly_adj.delivery_contract_mismatch")
        if receipt.intent["bootstrap"]:
            audited = dao.get_record(
                batch_id=context["execution_token"],
                record_kind="unit",
                unit_id="audit:" + unit.unit_id,
            )
            if (
                audited is None
                or audited.payload_digest != digest(audited.payload)
                or audited.scope_digest != context["scope_hash"]
                or audited.payload["summary"].get("source_digest")
                != receipt.payload_digest
            ):
                fail(
                    "首次单元尚未完成持久化对账",
                    "weekly_adj.delivery_contract_mismatch",
                )
            session.expunge(audited)
            summary = receipt.payload.get("summary", {})
            if "max_input_week" not in summary or (
                summary["max_input_week"] is None
            ) != (receipt.rows_written == 0):
                fail(
                    "首次刷新摘要缺少实际输入周",
                    "weekly_adj.delivery_contract_mismatch",
                )
            unit_max = summary["max_input_week"]
        else:
            unit_max = max(
                (
                    parse_day(row["trade_date"]).isoformat()
                    for row in receipt.payload["rows"]
                ),
                default=None,
            )
        if unit_max is not None:
            max_input_week = max(max_input_week or unit_max, unit_max)
        summaries.append({"unit_id": unit.unit_id, "digest": receipt.payload_digest})
        received += receipt.rows_received
        written += receipt.rows_written
        preserved += receipt.rows_preserved
        total_bytes += canonical_json_size(receipt.payload)
        session.expunge(receipt)
    if total_bytes > policy.max_batch_payload_bytes:
        fail("整批载荷超过预算", "weekly_adj.row_budget_exceeded")
    header = {
        "unit_count": len(unit_ids),
        "total_payload_bytes": total_bytes,
        "units_digest": digest(summaries),
        "bootstrap": context["business_plan"]["metadata"]["bootstrap"],
        "contract_digest": context["contract_digest"],
        "max_input_week": max_input_week,
    }
    payload = {"header": header, "unit_ids": unit_ids}
    metadata = context["business_plan"]["metadata"]
    if metadata["bootstrap"]:
        payload["bootstrap_reconciled"] = True
        if metadata.get("bootstrap_parent_batch"):
            payload["bootstrap_parent"] = {
                "batch_id": metadata["bootstrap_parent_batch"],
                "revision": metadata["bootstrap_parent_revision"],
            }
    check()
    return dao.append(
        delivery_record(
            context=context,
            kind="batch_closed",
            unit_id="batch_closed",
            payload=payload,
            rows_received=received,
            rows_unique=written,
            rows_written=written,
            rows_preserved=preserved,
        ),
        policy,
    )
