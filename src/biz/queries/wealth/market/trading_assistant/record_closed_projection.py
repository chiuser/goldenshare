"""Closed-sale evidence from the fixed publication, not current quote estimates."""
from sqlalchemy import and_, func, select, tuple_
from sqlalchemy.orm import aliased

from src.biz.models.wealth.trading_assistant.accounts import InitialPosition
from src.biz.models.wealth.trading_assistant.calculation import CalculationGeneration, DayResult, PositionState
from src.biz.models.wealth.trading_assistant.publication import PublicationDay
from src.biz.schemas.wealth.market.trading_assistant.records import ClosedTrade
from src.biz.services.wealth.market.trading_assistant.account_acceptance import accepted_time
from src.biz.services.wealth.market.trading_assistant.calculation.precision import format_cents, round_ratio_half_up
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.persistence_values import numeric_cents, quantity_text


def closed_metadata(session, rows, *, deadline, policy):
    """Two batched SQL reads for an already bounded page of published sales."""
    if not rows:
        return {}, {}
    end, opening = aliased(PositionState), aliased(PositionState)
    previous = aliased(PublicationDay)
    pub = PublicationDay
    prior_id = select(previous.day_result_id).where(previous.account_id == pub.account_id,
        previous.generation_id == pub.generation_id, previous.trade_date < pub.trade_date
    ).order_by(previous.trade_date.desc()).limit(1).correlate(pub).scalar_subquery()
    keys = {(r.account_id, r.published_id, r.day_result_id, r.ts_code, r.round_id) for r in rows}
    statement = select(pub.account_id, pub.generation_id, pub.day_result_id, end.ts_code, end.round_id,
        end.quantity.label("end_quantity"), CalculationGeneration.rule_version,
        opening.quantity.label("opening_quantity"), opening.remaining_buy_cost,
        InitialPosition.cost_price.label("initial_cost")
    ).select_from(pub).join(DayResult, and_(DayResult.account_id == pub.account_id,
        DayResult.day_result_id == pub.day_result_id, DayResult.status == "SEALED")
    ).join(CalculationGeneration, and_(CalculationGeneration.account_id == DayResult.account_id,
        CalculationGeneration.generation_id == DayResult.origin_generation_id)
    ).join(end, and_(end.account_id == pub.account_id, end.day_result_id == pub.day_result_id)
    ).outerjoin(opening, and_(opening.account_id == pub.account_id, opening.day_result_id == prior_id,
        opening.ts_code == end.ts_code, opening.round_id == end.round_id)
    ).outerjoin(InitialPosition, and_(InitialPosition.account_id == pub.account_id,
        InitialPosition.initialization_id == CalculationGeneration.initialization_id,
        InitialPosition.ts_code == end.ts_code, InitialPosition.opened_on == pub.trade_date)
    ).where(tuple_(pub.account_id, pub.generation_id, pub.day_result_id, end.ts_code, end.round_id).in_(keys))
    apply_sql_budget(session, deadline, policy)
    metadata = {(r.account_id, r.generation_id, r.day_result_id, r.ts_code, r.round_id): r
                for r in session.execute(statement)}
    # Number every round of these account/stock pairs before selecting requested
    # IDs. Applying the page filter first would incorrectly number every round 1.
    groups = select(pub.account_id, pub.generation_id, PositionState.ts_code, PositionState.round_id,
        func.min(PositionState.opened_on).label("opened_on"), func.max(PositionState.closed_on).label("closed_on")
    ).join(PositionState, and_(PositionState.account_id == pub.account_id,
        PositionState.day_result_id == pub.day_result_id)
    ).where(tuple_(pub.account_id, pub.generation_id, PositionState.ts_code).in_(
        {(r.account_id, r.published_id, r.ts_code) for r in rows})
    ).group_by(pub.account_id, pub.generation_id, PositionState.ts_code, PositionState.round_id).subquery()
    numbered = select(groups, func.row_number().over(
        partition_by=(groups.c.account_id, groups.c.generation_id, groups.c.ts_code),
        order_by=(groups.c.opened_on, groups.c.round_id)).label("round_number")).subquery()
    apply_sql_budget(session, deadline, policy)
    rounds = {(r.account_id, r.generation_id, r.ts_code, r.round_id): r for r in session.execute(
        select(numbered).where(tuple_(numbered.c.account_id, numbered.c.generation_id,
            numbered.c.ts_code, numbered.c.round_id).in_(
                {(r.account_id, r.published_id, r.ts_code, r.round_id) for r in rows})))}
    return metadata, rounds


def project_closed(row, *, account_ref, stock_ref, metadata, rounds):
    info = metadata[(row.account_id, row.published_id, row.day_result_id, row.ts_code, row.round_id)]
    round_info = rounds[(row.account_id, row.published_id, row.ts_code, row.round_id)]
    if info.opening_quantity is not None and info.opening_quantity > 0:
        unit_cost = round_ratio_half_up(numeric_cents(info.remaining_buy_cost), int(info.opening_quantity))
    elif info.initial_cost is not None:
        unit_cost = numeric_cents(info.initial_cost)
    else:
        raise ValueError("Published closed sale has no opening cost evidence")
    money = lambda value: format_cents(numeric_cents(value))
    return ClosedTrade(accountRef=account_ref, stockRef=stock_ref, tradeId=str(row.ledger_id),
        sellRevision=str(row.revision), tradeDate=row.occurred_on.isoformat(), recordedAt=accepted_time(row.recorded_at),
        roundRef=dict(accountId=str(row.account_id), roundId=str(row.round_id), roundNumber=round_info.round_number,
            status="CLOSED" if round_info.closed_on is not None else "OPEN"),
        quantity=row.quantity, price=money(row.price), grossAmount=money(row.gross_amount),
        commissionAmount=money(row.commission_amount), stampTaxAmount=money(row.stamp_tax_amount),
        totalFeeAmount=format_cents(numeric_cents(row.commission_amount) + numeric_cents(row.stamp_tax_amount)),
        netProceeds=money(row.net_cash_change), dayOpeningUnitCost=format_cents(unit_cost),
        allocatedCost=money(row.allocated_cost), dayEndQuantity=quantity_text(info.end_quantity),
        dayGroup=dict(accountId=str(row.account_id), tsCode=row.ts_code, tradeDate=row.occurred_on.isoformat()),
        calculationRuleVersion=str(info.rule_version), dayResultId=str(row.day_result_id),
        profitAmount=money(row.closed_profit_amount), returnPct=money(row.closed_return_pct))
