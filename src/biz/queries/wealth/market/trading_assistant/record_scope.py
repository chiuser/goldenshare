"""Owned record labels and availability; no valuation is required for raw facts."""
from datetime import date
from uuid import UUID

from sqlalchemy import select

from src.foundation.models.core_serving.security_serving import Security
from src.biz.models.wealth.trading_assistant.accounts import Account
from src.biz.schemas.wealth.market.trading_assistant.common import AccountRef, AccountCoverage, Coverage, Scope, StockRef
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from src.biz.services.wealth.market.trading_assistant.write_protocol import WriteProtocolConflict


def read_record_scope(session, *, owner_id, basis, query, deadline, policy):
    refs, covers = [], []
    ids = [UUID(ref.accountId) for ref in basis.context.accounts]
    for offset in range(0, len(ids), policy.page_rows):
        apply_sql_budget(session, deadline, policy)
        accounts = session.scalars(select(Account).where(Account.owner_id == owner_id,
            Account.account_id.in_(ids[offset:offset + policy.page_rows])).order_by(Account.account_id)).all()
        for account in accounts:
            refs.append(AccountRef(accountId=str(account.account_id), name=account.name, brokerName=account.broker_name))
            start = max(account.initialized_on, date.fromisoformat(query.requestedStartDate))
            end = date.fromisoformat(query.requestedEndDate)
            covers.append(AccountCoverage(accountId=str(account.account_id), initializedOn=account.initialized_on.isoformat(),
                effectiveStartDate=start.isoformat() if start <= end else None,
                targetThroughDate=end.isoformat() if start <= end else None,
                calculatedThroughDate=None, valuationAt=None, dataStatus="Ready", reason=None))
    if [r.accountId for r in refs] != [r.accountId for r in basis.context.accounts]:
        raise WriteProtocolConflict("TA_READ_CONTEXT_CHANGED")
    code = getattr(query, "tsCode", None)
    names = read_record_names(session, [code] if code else [], deadline=deadline, policy=policy)
    scope = Scope(accountMode=query.accountMode, accounts=refs, stockMode="SINGLE" if code else "ALL",
        stockRef=StockRef(tsCode=code, name=names[code]) if code else None)
    coverage = Coverage(dataStatus="Ready" if refs else "Empty", reason=None, isFinal=True, accounts=covers)
    return scope, coverage


def read_record_names(session, codes, *, deadline, policy):
    codes = sorted(set(codes))
    names = {}
    for offset in range(0, len(codes), policy.page_rows):
        apply_sql_budget(session, deadline, policy)
        names.update(session.execute(select(Security.ts_code, Security.name).where(
            Security.ts_code.in_(codes[offset:offset + policy.page_rows]))).all())
    if set(names) != set(codes) or any(not name for name in names.values()):
        raise WriteProtocolConflict("TA_OBJECT_NOT_FOUND")
    return names
