"""Fixed-version, keyset pages for M3; allocation ranks the whole sell day.

PostgreSQL NUMERIC div/mod retain arbitrary precision. LIMIT and the resume
predicate are outside the window, so a page boundary cannot redistribute cents.
"""
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Numeric, case, cast, func, literal, select

from .effective_ledger import effective_ledger
from src.biz.services.wealth.market.trading_assistant.calculation.precision import require_integer


def _scope(owner_id, account_id, fact_version, trade_date, stock):
    if type(trade_date) is not date or not stock or len(stock) > 16:
        raise ValueError("Invalid stock/day scope")
    facts = effective_ledger(owner_id=owner_id, account_id=account_id, fact_version=fact_version)
    return select(facts).where(facts.c.kind == "TRADE", facts.c.ts_code == stock,
                               facts.c.occurred_on == trade_date).subquery("stock_day")


def _limit(limit, policy, after):
    if type(limit) is not int or not 1 <= limit <= policy.page_rows:
        raise ValueError("Invalid calculation page size")
    if after is not None and not isinstance(after, UUID):
        raise ValueError("Invalid stable source cursor")


def trade_page(*, owner_id, account_id, fact_version, trade_date, stock, limit, policy, after=None):
    _limit(limit, policy, after)
    rows = _scope(owner_id, account_id, fact_version, trade_date, stock)
    # Do not materialize remarks, recovery payloads or other unbounded text.
    names = ("ledger_id", "revision", "direction", "quantity", "price", "gross_amount",
             "commission_rate", "minimum_commission", "stamp_tax_rate", "commission_amount",
             "stamp_tax_amount", "net_cash_change")
    query = select(*(rows.c[name] for name in names))
    if after is not None:
        query = query.where(rows.c.ledger_id > after)
    return query.order_by(rows.c.ledger_id).limit(limit)


def allocated_sell_page(*, owner_id, account_id, fact_version, trade_date, stock,
                        opening_quantity, opening_pool_cents, limit, policy, after=None):
    """Return whole-day totals on each bounded row for independent conservation checks."""
    _limit(limit, policy, after)
    require_integer(opening_quantity, minimum=1)
    require_integer(opening_pool_cents, minimum=0)
    rows = _scope(owner_id, account_id, fact_version, trade_date, stock)
    pool = literal(Decimal(opening_pool_cents), type_=Numeric())
    quantity = literal(Decimal(opening_quantity), type_=Numeric())
    product = pool * cast(rows.c.quantity, Numeric())
    bases = select(rows.c.ledger_id, rows.c.revision, rows.c.quantity, rows.c.net_cash_change,
                   func.div(product, quantity).label("base_cost_cents"),
                   func.mod(product, quantity).label("remainder")).where(
                       rows.c.direction == "SELL").subquery("sell_bases")
    ranked = select(bases,
        func.row_number().over(order_by=(bases.c.remainder.desc(), bases.c.ledger_id)).label("cost_rank"),
        func.sum(cast(bases.c.quantity, Numeric())).over().label("total_sold"),
        func.sum(bases.c.base_cost_cents).over().label("total_base"),
        func.count().over().label("sell_count")).subquery("ranked_sells")
    # HALF_UP for nonnegative pool/quantity using integer division, not rounded '/'.
    target = func.div(2 * pool * ranked.c.total_sold + quantity, 2 * quantity)
    final_cost = ranked.c.base_cost_cents + case(
        (ranked.c.cost_rank <= target - ranked.c.total_base, 1), else_=0)
    query = select(ranked.c.ledger_id, ranked.c.revision, ranked.c.quantity,
                   ranked.c.net_cash_change, final_cost.label("allocated_cost_cents"),
                   target.label("allocation_target_cents"), ranked.c.total_sold, ranked.c.sell_count)
    if after is not None:
        query = query.where(ranked.c.ledger_id > after)
    return query.order_by(ranked.c.ledger_id).limit(limit)
