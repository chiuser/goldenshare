"""Fixed-fact-version cash movement pages, including non-trading dates."""
from datetime import date

from sqlalchemy import select

from .calculation_ledger import _limit
from .effective_ledger import effective_ledger


def cash_day_page(*, owner_id, account_id, fact_version, business_date, limit, policy, after=None):
    _limit(limit, policy, after)
    if type(business_date) is not date:
        raise ValueError("Invalid cash business date")
    facts = effective_ledger(owner_id=owner_id, account_id=account_id, fact_version=fact_version)
    query = select(*(facts.c[key] for key in (
        "ledger_id", "revision", "kind", "direction", "net_cash_change"))).where(
            facts.c.occurred_on == business_date)
    if after is not None:
        query = query.where(facts.c.ledger_id > after)
    return query.order_by(facts.c.ledger_id).limit(limit)
