"""Paginated historical stock contributions in one fixed account read snapshot."""
from heapq import merge
from itertools import groupby
from uuid import UUID

from sqlalchemy import and_, case, func, literal, select, union_all

from src.biz.models.wealth.trading_assistant.accounts import InitialPosition
from src.biz.models.wealth.trading_assistant.calculation import PositionState
from src.biz.models.wealth.trading_assistant.publication import PublicationDay
from src.biz.schemas.wealth.market.trading_assistant.common import StockRef
from src.biz.schemas.wealth.market.trading_assistant.positions import AccountRound
from src.biz.schemas.wealth.market.trading_assistant.returns import DayContribution, DayContributions
from src.biz.services.wealth.market.trading_assistant.calculation.precision import format_cents
from src.biz.services.wealth.market.trading_assistant.calculation.returns import profit_result
from src.biz.services.wealth.market.trading_assistant.market_facts import apply_sql_budget
from .effective_ledger import effective_ledger
from .record_cursor import RecordCursor
from .record_scope import read_record_names
from .return_day_detail import ReturnDayDetailQuery
from .return_stock_days import PublishedStockReturnDaysQuery


def contribution_key(value):
    if not isinstance(value, str) or not value or len(value) > 32:
        raise ValueError("Invalid contribution cursor key")
    return value


def contribution_page(streams, *, after, limit, deadline):
    """Merge bounded account streams; retain only one output page and scalar totals."""
    selected, count, profit, complete = [], 0, 0, True
    for code, values in groupby(merge(*streams, key=lambda row: row[0]), key=lambda row: row[0]):
        deadline.remaining_ms()
        parts = list(values)  # At most one part per selected account, not the full history.
        issues = [part for part in parts if part[2] != "Ready"]
        ready = not issues
        amount = sum(part[1].result.profit_cents for part in parts) if ready else None
        capital = sum(part[1].result.capital_cents for part in parts) if ready else None
        count += 1
        complete = complete and ready
        profit += amount if amount is not None else 0
        if (after is None or code > after) and len(selected) <= limit:
            state = ("Partial" if any(part[2] == "Ready" for part in parts) else issues[0][2]) if issues else "Ready"
            result = profit_result(amount, capital, participates=True) if ready else None
            selected.append(dict(code=code, profitAmount=format_cents(amount) if ready else None,
                capitalAmount=format_cents(capital) if ready else None,
                returnPct=result.return_pct if result else None, dataStatus=state,
                reason=issues[0][3] if issues else None,
                accountRounds=[part[4] for part in parts if part[4] is not None]))
    return selected[:limit], count, profit if complete else None, len(selected) > limit


class ReturnContributionsQuery:
    def __init__(self, policy):
        self.policy = policy
        self.detail = ReturnDayDetailQuery(policy)
        self.stocks = PublishedStockReturnDaysQuery(policy)

    def _unavailable(self, session, *, scope, day, cover, deadline):
        """Keep known participants even when their account has no published result."""
        account_id = UUID(scope.account.accountId)
        ledger = effective_ledger(owner_id=scope.owner_id, account_id=account_id, fact_version=scope.fact_version)
        initial = select(InitialPosition.ts_code, InitialPosition.quantity.label("quantity"),
            literal(0).label("trades")).where(InitialPosition.account_id == account_id,
                InitialPosition.initialization_id == scope.initialization_id, InitialPosition.opened_on <= day)
        trades = select(ledger.c.ts_code,
            case((ledger.c.direction == "BUY", ledger.c.quantity), else_=-ledger.c.quantity).label("quantity"),
            case((ledger.c.occurred_on == day, 1), else_=0).label("trades")).where(
                ledger.c.kind == "TRADE", ledger.c.occurred_on <= day)
        events = union_all(initial, trades).subquery()
        codes = select(events.c.ts_code).group_by(events.c.ts_code).having(
            (func.sum(events.c.quantity) > 0) | (func.sum(events.c.trades) > 0))
        after = None
        while True:
            apply_sql_budget(session, deadline, self.policy)
            query = codes.where(events.c.ts_code > after) if after else codes
            page = session.scalars(query.order_by(events.c.ts_code).limit(self.policy.page_rows)).all()
            for code in page:
                yield code, None, cover.dataStatus, cover.reason, None
            if len(page) < self.policy.page_rows:
                return
            after = page[-1]

    def _ready(self, session, *, owner_id, basis, account_id, day, deadline):
        reference = next(ref for ref in basis.context.accounts if ref.accountId == str(account_id))
        generation_id, after = UUID(reference.publishedGenerationId), None
        while True:
            page = self.stocks.page(session, owner_id=owner_id, basis=basis, account_id=account_id,
                day=day, deadline=deadline, after_stock=after)
            codes = [item.endpoint.stock for item in page.items]
            apply_sql_budget(session, deadline, self.policy)
            rounds = dict(session.execute(select(PositionState.ts_code, func.count(func.distinct(PositionState.round_id)))
                .join(PublicationDay, and_(PublicationDay.account_id == PositionState.account_id,
                    PublicationDay.day_result_id == PositionState.day_result_id)).where(
                    PublicationDay.account_id == account_id, PublicationDay.generation_id == generation_id,
                    PublicationDay.trade_date <= day, PositionState.ts_code.in_(codes))
                .group_by(PositionState.ts_code)).all()) if codes else {}
            for item in page.items:
                endpoint = item.endpoint
                yield endpoint.stock, item, "Ready", None, AccountRound(accountId=str(account_id),
                    roundId=str(endpoint.round_id), roundNumber=int(rounds[endpoint.stock]))
            if page.next_stock is None:
                return
            after = page.next_stock

    def read(self, session, *, owner_id, basis, query, cutoff, deadline, day):
        detail = self.detail.read(session, owner_id=owner_id, account_mode=query.accountMode,
            basis=basis, cutoff=cutoff, deadline=deadline, day=day)
        cursor = RecordCursor(kind="DAY_CONTRIBUTIONS", filters=dict(date=day.isoformat(),
            accountMode=query.accountMode, accountId=query.accountId, limit=query.limit), context=basis.context)
        after = cursor.decode(query.cursor, validate_key=contribution_key)
        streams = []
        for cover in detail.coverage.accounts:
            if cover.dataStatus == "Empty":
                continue
            account_id = UUID(cover.accountId)
            if cover.dataStatus == "Ready":
                streams.append(self._ready(session, owner_id=owner_id, basis=basis,
                    account_id=account_id, day=day, deadline=deadline))
            else:
                scope = self.stocks.scopes.read(session, owner_id=owner_id, basis=basis,
                    account_id=account_id, deadline=deadline)
                streams.append(self._unavailable(session, scope=scope, day=day, cover=cover, deadline=deadline))
        rows, count, total, more = contribution_page(streams, after=after, limit=query.limit, deadline=deadline)
        if detail.coverage.dataStatus == "Ready" and (total is None or format_cents(total) != detail.profitAmount):
            raise ValueError("Stock contributions do not reconcile to the fixed account day")
        names = read_record_names(session, [row["code"] for row in rows], deadline=deadline, policy=self.policy)
        items = [DayContribution(stockRef=StockRef(tsCode=row["code"], name=names[row["code"]]),
            **{k: v for k, v in row.items() if k != "code"}) for row in rows]
        return DayContributions(items=items, nextCursor=cursor.encode(rows[-1]["code"]) if more else None,
            scope=detail.scope, date=day.isoformat(), readContext=basis.context, coverage=detail.coverage,
            totalCount=count, totalProfitAmount=detail.profitAmount)
