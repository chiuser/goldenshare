"""Explicit initial holding dates; never infer a date or an unrecorded trade."""
from datetime import date

from sqlalchemy import select

from src.biz.models.wealth.trading_assistant.accounts import InitialPosition
from src.biz.schemas.wealth.market.trading_assistant.accounts import InitializationPositionInput
from .calculation.precision import format_cents
from .persistence_values import numeric_cents
from .market_facts import apply_sql_budget


class InvalidInitializationDate(ValueError):
    def __init__(self, row, message):
        super().__init__(message)
        self.client_row_id = row.clientRowId
        self.message = message
        self.field = "initialPositions.openedOn"


def validate_opened_on(session, row, *, initialized_on, market, security, deadline,
                       upper_bound_message="建仓日期不能晚于首次录入日期。"):
    opened = date.fromisoformat(row.openedOn)
    if opened > initialized_on:
        raise InvalidInitializationDate(row, upper_bound_message)
    basis = market.read_calendar(session, security.exchange, opened, opened, deadline)
    if not basis.days[0].is_open:
        raise InvalidInitializationDate(row, "请选择实际建仓的交易日。")
    return {"exchange": security.exchange, "openedOn": row.openedOn,
            "sourceVersion": basis.source_version}


def affected_initialization_date(initialized_on, before, after, *, cash_changed):
    """Inputs are aligned normalized row DTOs, not current derived holdings."""
    old, new = ({row.tsCode: row for row in rows} for rows in (before, after))
    dates = [initialized_on] if cash_changed else []
    for code in old.keys() | new.keys():
        left, right = old.get(code), new.get(code)
        if left is None or right is None:
            dates.append(date.fromisoformat((left or right).openedOn))
            continue
        if any(getattr(left, f) != getattr(right, f) for f in ("openedOn", "quantity", "costPrice")):
            dates.extend(date.fromisoformat(row.openedOn) for row in (left, right))
        if left.availableQuantity != right.availableQuantity:
            dates.append(initialized_on)
    return min(dates, default=initialized_on)


def read_initial_rows(session, initialization_id, *, policy, deadline):
    after = None
    while True:
        apply_sql_budget(session, deadline, policy)
        query = select(InitialPosition).where(InitialPosition.initialization_id == initialization_id)
        if after is not None:
            query = query.where(InitialPosition.ts_code > after)
        rows = session.scalars(query.order_by(InitialPosition.ts_code).limit(policy.page_rows)).all()
        for row in rows:
            yield InitializationPositionInput(clientRowId=row.client_row_id, tsCode=row.ts_code,
                openedOn=row.opened_on.isoformat(), quantity=row.quantity,
                availableQuantity=row.available_quantity, costPrice=format_cents(numeric_cents(row.cost_price)))
        if len(rows) < policy.page_rows:
            break
        after = rows[-1].ts_code
